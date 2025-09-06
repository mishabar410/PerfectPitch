"""Upload endpoints for presentations and auxiliary files.

POST /uploads/{session_id} accepts multipart form-data with a single file field.
The filename determines how it is stored (e.g., pptx.pptx, meta.json, data.json).
"""

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.paths import UPLOADS_DIR


router = APIRouter()


@router.post("/uploads/{session_id}")
async def upload_files(session_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    filename = file.filename or "uploaded.bin"
    dest = folder / filename
    content = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "saved_as": f"uploads/{session_id}/{filename}"}


