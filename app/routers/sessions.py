"""Session lifecycle endpoints: create and delete session directories."""

import json
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.core.paths import UPLOADS_DIR, ARTIFACTS_DIR


router = APIRouter()


@router.post("/sessions")
def create_session() -> Dict[str, Any]:
    session_id = uuid.uuid4().hex
    folder = UPLOADS_DIR / session_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps({"session_id": session_id}, ensure_ascii=False), encoding="utf-8")
    return {
        "session_id": session_id,
        "upload_urls": {
            "files": f"/uploads/{session_id}",
            "audio_chunk": f"/audio/{session_id}/chunk",
            "audio_finalize": f"/audio/{session_id}/finalize",
        },
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    art = ARTIFACTS_DIR / session_id
    if not folder.exists() and not art.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    import shutil
    if folder.exists():
        shutil.rmtree(folder)
    if art.exists():
        shutil.rmtree(art)
    return {"ok": True}


