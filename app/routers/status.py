"""Status endpoint for background task progress."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services.tasks import get_task


router = APIRouter()


@router.get("/status/{task_id}")
def get_status(task_id: str) -> Dict[str, Any]:
    info = get_task(task_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "state": info.state,
        "stage": info.stage,
        "progress_pct": info.progress_pct,
        "error_code": info.error_code,
        "error_message": info.error_message,
    }


