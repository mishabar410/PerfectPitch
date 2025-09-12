import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.paths import ARTIFACTS_DIR, UPLOADS_DIR
import logging
from app.services.pptx_parser import parse_pptx_metrics
from app.services.transcription import transcribe_audio
from app.services.judge import (
    slice_transcript_by_datajson,
    judge_slides_batched,
    generate_feedback_and_questions,
    judge_script_vs_speech,
    review_script_quality,
)
from app.services.pptx_render import render_pptx_to_images
from app.services.doc_parser import parse_word_script
from app.services.speech_quality import compute_speech_quality


@dataclass
class TaskInfo:
    """In-memory progress/state for a background processing task."""
    state: str = "PENDING"  # PENDING | RUNNING | FAILED | DONE
    stage: Optional[str] = None  # asr|parse|judge|assemble
    progress_pct: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    session_id: Optional[str] = None


_tasks_lock = threading.Lock()
_tasks: Dict[str, TaskInfo] = {}
_executor = ThreadPoolExecutor(max_workers=2)


def _set(task_id: str, **kwargs: Any) -> None:
    with _tasks_lock:
        info = _tasks.get(task_id)
        if info is None:
            info = TaskInfo()
        for k, v in kwargs.items():
            setattr(info, k, v)
        _tasks[task_id] = info


def get_task(task_id: str) -> Optional[TaskInfo]:
    with _tasks_lock:
        return _tasks.get(task_id)


def _find_presentation(folder: Path) -> Optional[Path]:
    for name in ["pptx.pptm", "pptx.pptx", "presentation.pptx"]:
        p = folder / name
        if p.exists():
            return p
    return None


def _find_audio(folder: Path) -> Optional[Path]:
    for name in ["audio.webm", "video.mp4", "audio.wav", "audio.m4a", "audio.mp3"]:
        p = folder / name
        if p.exists():
            return p
    return None


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _pipeline(session_id: str, task_id: str) -> None:
    """Run end-to-end pipeline for a session: parse, asr, judge, assemble."""
    lg = logging.getLogger(__name__)
    try:
        lg.info("pipeline_start", extra={"session_id": session_id, "task_id": task_id})
        _set(task_id, state="RUNNING", stage="parse", progress_pct=5, session_id=session_id)
        folder = UPLOADS_DIR / session_id
        out_dir = ARTIFACTS_DIR / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            _write_json(out_dir / "status.json", asdict(_tasks.get(task_id) or TaskInfo()))
        except Exception:
            pass

        data = _load_json(folder / "data.json")
        meta = _load_json(folder / "meta.json")

        ppt_path = _find_presentation(folder)
        if ppt_path is None:
            raise FileNotFoundError("Presentation not found")

        slides_content, deck_metrics = parse_pptx_metrics(ppt_path)
        _write_json(out_dir / "slides.json", {"slides": slides_content, "metrics": deck_metrics})
        lg.info("pptx_parsed", extra={"slides": len(slides_content)})

        # Render slide images for multimodal judging
        images_dir = out_dir / "slides"
        image_paths = []
        try:
            image_paths = render_pptx_to_images(ppt_path, images_dir)
        except Exception:
            image_paths = []
        lg.info("pptx_render", extra={"images": len(image_paths)})

        _set(task_id, stage="asr", progress_pct=30)
        try:
            _write_json(out_dir / "status.json", asdict(_tasks.get(task_id) or TaskInfo()))
        except Exception:
            pass
        audio_path = _find_audio(folder)
        if audio_path is None:
            raise FileNotFoundError("Audio/Video not found")
        transcript = transcribe_audio(audio_path, lang_hint=data.get("lang_hint"))
        (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
        lg.info("asr_done", extra={"chars": len(transcript)})

        _set(task_id, stage="judge", progress_pct=60)
        try:
            _write_json(out_dir / "status.json", asdict(_tasks.get(task_id) or TaskInfo()))
        except Exception:
            pass
        per_slide_text = slice_transcript_by_datajson(transcript, data)
        # Compute durations per slide from data.json if provided
        durations_ms_by_index: Dict[int, int] = {}
        for sl in data.get("slides", []) or []:
            try:
                idx = int(sl.get("index"))
                start_ms = int(sl.get("start_ms")) if sl.get("start_ms") is not None else None
                end_ms = int(sl.get("end_ms")) if sl.get("end_ms") is not None else None
                if start_ms is not None and end_ms is not None and end_ms >= start_ms:
                    durations_ms_by_index[idx] = end_ms - start_ms
            except Exception:
                continue
        image_map = {i + 1: p for i, p in enumerate(image_paths)} if image_paths else None
        per_slide_results = judge_slides_batched(slides_content, per_slide_text, batch_size=3, image_path_by_index=image_map)
        # Attach ASR transcript slice per slide to results
        for r in per_slide_results:
            try:
                idx = int(r.get("index"))
            except Exception:
                idx = None
            if idx is not None and idx in per_slide_text:
                r["transcript"] = per_slide_text[idx]
            if idx is not None and idx in durations_ms_by_index:
                r["duration_ms"] = durations_ms_by_index[idx]

        sims = []
        for r in per_slide_results:
            try:
                sims.append(float(r.get("similarity_0_1", 0.0)))
            except Exception:
                sims.append(0.0)
        similarity_avg = round(sum(sims) / max(1, len(sims)), 3)

        weak_by_density = deck_metrics.get("text_density", {}).get("bad_on", [])
        weak_by_fonts = deck_metrics.get("small_fonts", [])
        weak_by_similarity = [r.get("index") for r in per_slide_results if r.get("similarity_0_1", 1.0) < 0.5]
        weak_slides = sorted(list({*weak_by_density, *weak_by_fonts, *weak_by_similarity}))

        improvements, questions = generate_feedback_and_questions(weak_slides, deck_metrics, per_slide_results)
        lg.info("judge_done", extra={"similarity_avg": similarity_avg, "weak_slides": weak_slides})

        # Optional: compare uploaded script (Word) to transcript and review script quality
        script_candidates = [folder / "word.docx", folder / "word.docm", folder / "script.docx", folder / "script.docm", folder / "word.doc"]
        script_path = next((p for p in script_candidates if p.exists()), None)
        script_eval = None
        script_quality = None
        if script_path is not None:
            parsed = parse_word_script(script_path)
            script_text = parsed.get("text", "")
            if script_text:
                script_eval = judge_script_vs_speech(script_text, transcript)
                script_quality = review_script_quality(script_text)
        lg.info("script_eval", extra={"present": script_path is not None})
        overall_score = round(similarity_avg * 100.0, 1)

        # Speech quality metrics
        _set(task_id, stage="speech_quality", progress_pct=92)
        try:
            _write_json(out_dir / "status.json", asdict(_tasks.get(task_id) or TaskInfo()))
        except Exception:
            pass
        speech_quality = compute_speech_quality(audio_path, transcript, data, per_slide_text)
        lg.info("speech_quality", extra={"available": bool(speech_quality.get("available"))})

        _set(task_id, stage="assemble", progress_pct=95)
        report: Dict[str, Any] = {
            "uuid": session_id,
            "models": {"stt": "whisper-1", "judge": "gpt-4o-mini"},
            "overall_score": overall_score,
            "delivery": {"slide_speech_similarity_avg": similarity_avg},
            "slides": {"per_slide": per_slide_results},
            "presentation_quality": deck_metrics,
            "questions": questions,
            "script": {
                "present": script_path is not None,
                "eval": script_eval,
                "quality": script_quality,
            },
            "speech_quality": speech_quality,
        }
        (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "feedback.md").write_text("\n".join(f"- {imp}" for imp in improvements), encoding="utf-8")
        (out_dir / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")

        _set(task_id, state="DONE", stage="assemble", progress_pct=100)
        try:
            _write_json(out_dir / "status.json", asdict(_tasks.get(task_id) or TaskInfo()))
        except Exception:
            pass
        lg.info("pipeline_done", extra={"task_id": task_id})
    except Exception as e:
        _set(task_id, state="FAILED", error_code="PIPELINE_ERROR", error_message=str(e))
        lg.exception("pipeline_failed", extra={"task_id": task_id})


def start_process(session_id: str) -> str:
    """Submit a background processing job and return its task_id."""
    task_id = uuid.uuid4().hex
    _set(task_id, state="PENDING", progress_pct=0)
    _executor.submit(_pipeline, session_id, task_id)
    return task_id


