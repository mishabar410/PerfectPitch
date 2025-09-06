"""Audio chunk upload and finalize endpoints for recorded speech.

Chunks are appended to uploads/{session_id}/audio.webm.part and later finalized
to uploads/{session_id}/audio.webm.
"""

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.paths import UPLOADS_DIR


router = APIRouter()


@router.post("/audio/{session_id}/chunk")
async def upload_audio_chunk(session_id: str, chunk: UploadFile = File(...)) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    path = folder / "audio.webm.part"
    # append chunk bytes
    data = await chunk.read()
    with open(path, "ab") as f:
        f.write(data)
    return {"ok": True}


@router.post("/audio/{session_id}/finalize")
def finalize_audio(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    part = folder / "audio.webm.part"
    final = folder / "audio.webm"
    if not part.exists():
        raise HTTPException(status_code=400, detail="No chunks uploaded")
    part.rename(final)
    return {"ok": True, "audio": f"uploads/{session_id}/audio.webm"}


