"""Objections (questions) generation based on transcript and meta.

GET /questions/{session_id} — returns generated objections with answers for roles.
"""

from typing import Any, Dict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.paths import UPLOADS_DIR, ARTIFACTS_DIR
from app.services.judge import generate_objections_with_answers


router = APIRouter()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_json(path: Path) -> Dict[str, Any]:
    import json
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@router.get("/questions/{session_id}")
def get_questions(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    transcript = _read_text(folder / "transcript.txt")
    if not transcript:
        # fallback: pipeline writes transcript into artifacts/{sid}
        transcript = _read_text((ARTIFACTS_DIR / session_id) / "transcript.txt")
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript not found; record audio first.")
    meta = _load_json(folder / "meta.json")

    # Load extra context for more specific objections
    slides_payload = _load_json((ARTIFACTS_DIR / session_id) / "slides.json")
    deck_metrics = slides_payload.get("metrics") if isinstance(slides_payload, dict) else {}
    slides = slides_payload.get("slides") if isinstance(slides_payload, dict) else []

    data_json = _load_json(folder / "data.json")
    # Try to slice transcript per slide using data.json timings to provide windows
    try:
        from app.services.judge import slice_transcript_by_datajson
        per_slide_text = slice_transcript_by_datajson(transcript, data_json)
    except Exception:
        per_slide_text = {}

    # Load per-slide evaluation from report.json to identify weak spots
    report = _load_json((ARTIFACTS_DIR / session_id) / "report.json")
    per_slide_eval = []
    weak_slides = []
    try:
        ps = (report.get("slides") or {}).get("per_slide") or []
        for r in ps:
            idx = r.get("index")
            sim = r.get("similarity_0_1", 0.0)
            jdg = r.get("judgement", "")
            try:
                idx_i = int(idx)
            except Exception:
                continue
            per_slide_eval.append({"index": idx_i, "similarity_0_1": float(sim or 0.0), "judgement": jdg})
            if (sim or 0.0) < 0.6:
                weak_slides.append(idx_i)
    except Exception:
        per_slide_eval = []
        weak_slides = []

    res = generate_objections_with_answers(
        transcript,
        meta,
        slides=slides,
        per_slide_text=per_slide_text,
        deck_metrics=deck_metrics,
        per_slide_eval=per_slide_eval,
        weak_slides=weak_slides,
    )

    # persist for UI reuse
    out = ARTIFACTS_DIR / session_id
    out.mkdir(parents=True, exist_ok=True)
    try:
        import json
        (out / "objections.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return res


