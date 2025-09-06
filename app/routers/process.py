"""Process endpoint to kick off background analysis for a session."""

from fastapi import APIRouter, HTTPException

from app.core.paths import UPLOADS_DIR
from app.services.tasks import start_process


router = APIRouter()


@router.post("/process/{session_id}")
def process_uuid(session_id: str):
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Upload folder not found: {folder}")
    task_id = start_process(session_id)
    return {"task_id": task_id}


