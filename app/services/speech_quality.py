"""Speech quality metrics: speed, pauses, fillers, basic prosody.

Relies on ffmpeg for webm/mp4→wav conversion and librosa for analysis.
"""

import re
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import librosa
import numpy as np


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return True
    except Exception:
        return False


def _to_wav(input_path: Path, target_sr: int = 16000) -> Path:
    if input_path.suffix.lower() in {".wav"}:
        return input_path
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg not found; install to enable speech quality metrics")
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path), "-ac", "1", "-ar", str(target_sr), str(tmp)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return tmp


def _non_silent_intervals(y: np.ndarray, sr: int) -> List[Tuple[int, int]]:
    # Use librosa.effects.split to get non-silent (speech) intervals
    intervals = librosa.effects.split(y, top_db=30)
    return intervals.tolist() if hasattr(intervals, "tolist") else intervals


def _count_words(text: str) -> int:
    return len(re.findall(r"[\w\-']+", text, flags=re.UNICODE))


def _filler_counts(text: str) -> Dict[str, int]:
    t = text.lower()
    fillers = [
        r"\bэ+\b", r"\bэм+\b", r"\bээ+\b", r"\bну\b", r"\bкак бы\b", r"\bтипа\b",
        r"\bв общем\b", r"\bкороче\b", r"\bзначит\b", r"\bэто самое\b", r"\bскажем так\b",
        r"\bum+\b", r"\buh+\b", r"\blike\b",
    ]
    counts: Dict[str, int] = {}
    for pattern in fillers:
        counts[pattern] = len(re.findall(pattern, t, flags=re.UNICODE))
    return counts


def _pitch_stats(y: np.ndarray, sr: int) -> Tuple[Optional[float], Optional[float]]:
    try:
        f0, voiced_flag, voiced_probs = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
        f0 = np.array(f0)
        valid = f0[~np.isnan(f0)]
        if valid.size == 0:
            return None, None
        return float(np.nanmean(valid)), float(np.nanstd(valid))
    except Exception:
        return None, None


def compute_speech_quality(
    audio_path: Path,
    transcript_text: str,
    data_json: Optional[Dict[str, Any]] = None,
    per_slide_text: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """Compute speech metrics overall and per-slide (if data_json provided).

    Overall: WPM (by speaking time), pauses, fillers, pitch.
    Per-slide: same stats computed on the audio segment between start_ms..end_ms,
    and words/fillers taken from per_slide_text[idx] if provided.
    """
    try:
        wav_path = _to_wav(audio_path)
    except Exception as e:
        return {"available": False, "note": str(e)}

    y, sr = librosa.load(str(wav_path), sr=16000, mono=True)
    total_duration_s = y.shape[0] / sr if sr else 0.0
    intervals = _non_silent_intervals(y, sr)
    speech_durations = [int((end - start) / sr * 1000) for start, end in intervals]
    speaking_time_ms = int(sum(speech_durations))

    # Pause stats: gaps between intervals
    pauses_ms: List[int] = []
    last_end = 0
    for start, end in intervals:
        if start > last_end:
            pauses_ms.append(int((start - last_end) / sr * 1000))
        last_end = end
    # tail pause
    if last_end < len(y):
        pauses_ms.append(int((len(y) - last_end) / sr * 1000))

    words = _count_words(transcript_text)
    speaking_minutes = max(1e-9, speaking_time_ms / 60000.0)
    wpm = words / speaking_minutes

    # Filler words
    filler = _filler_counts(transcript_text)

    # Pitch
    pitch_mean_hz, pitch_std_hz = _pitch_stats(y, sr)

    # Per-slide detailed stats if timing provided
    per_slide_stats: List[Dict[str, Any]] = []
    if data_json and data_json.get("slides"):
        for sl in data_json["slides"]:
            try:
                idx = int(sl.get("index"))
                if sl.get("start_ms") is None or sl.get("end_ms") is None:
                    continue
                start_ms = int(sl["start_ms"])
                end_ms = int(sl["end_ms"])
                if end_ms <= start_ms:
                    continue
                start_samp = max(0, int(start_ms * sr / 1000))
                end_samp = min(len(y), int(end_ms * sr / 1000))
                seg = y[start_samp:end_samp]
                if seg.size == 0:
                    continue
                seg_intervals = _non_silent_intervals(seg, sr)
                seg_speaking_ms = int(sum((e - s) / sr * 1000 for s, e in seg_intervals))
                # pauses inside segment
                seg_pauses_ms: List[int] = []
                last_end = 0
                for s_i, e_i in seg_intervals:
                    if s_i > last_end:
                        seg_pauses_ms.append(int((s_i - last_end) / sr * 1000))
                    last_end = e_i
                if last_end < len(seg):
                    seg_pauses_ms.append(int((len(seg) - last_end) / sr * 1000))

                slide_text = (per_slide_text or {}).get(idx, "")
                slide_words = _count_words(slide_text)
                seg_minutes = max(1e-9, seg_speaking_ms / 60000.0)
                slide_wpm = slide_words / seg_minutes
                slide_fillers = _filler_counts(slide_text)
                seg_pitch_mean, seg_pitch_std = _pitch_stats(seg, sr)

                per_slide_stats.append({
                    "index": idx,
                    "duration_ms": end_ms - start_ms,
                    "speaking_time_ms": seg_speaking_ms,
                    "wpm": round(slide_wpm, 2),
                    "pauses": {
                        "count": len(seg_pauses_ms),
                        "avg_ms": int(np.mean(seg_pauses_ms)) if seg_pauses_ms else 0,
                        "p90_ms": int(np.percentile(seg_pauses_ms, 90)) if seg_pauses_ms else 0,
                        "over_700ms": int(sum(1 for p in seg_pauses_ms if p >= 700)),
                    },
                    "fillers": slide_fillers,
                    "pitch_mean_hz": seg_pitch_mean,
                    "pitch_std_hz": seg_pitch_std,
                })
            except Exception:
                continue

    metrics = {
        "available": True,
        "total_duration_ms": int(total_duration_s * 1000),
        "speaking_time_ms": speaking_time_ms,
        "wpm": round(wpm, 2),
        "pauses": {
            "count": len(pauses_ms),
            "avg_ms": int(np.mean(pauses_ms)) if pauses_ms else 0,
            "p90_ms": int(np.percentile(pauses_ms, 90)) if pauses_ms else 0,
            "over_700ms": int(sum(1 for p in pauses_ms if p >= 700)),
        },
        "fillers": filler,
        "pitch_mean_hz": pitch_mean_hz,
        "pitch_std_hz": pitch_std_hz,
        "per_slide_detailed": per_slide_stats,
    }
    return metrics


