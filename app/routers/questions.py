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

    # Simplified generation: use only transcript and meta to speed up
    res = generate_objections_with_answers(transcript, meta)

    # persist for UI reuse
    out = ARTIFACTS_DIR / session_id
    out.mkdir(parents=True, exist_ok=True)
    try:
        import json
        (out / "objections.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return res


