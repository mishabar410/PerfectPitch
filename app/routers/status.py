"""Status endpoint for background task progress."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services.tasks import get_task
from app.core.paths import ARTIFACTS_DIR


router = APIRouter()


@router.get("/status/{task_id}")
def get_status(task_id: str) -> Dict[str, Any]:
    info = get_task(task_id)
    if info is None:
        # Fallback to file-based status if available (pipeline may have completed after reload)
        from pathlib import Path
        import json
        # Try to scan artifacts for a status.json that references this task_id is not feasible without index,
        # but we can treat missing in-memory as DONE if report.json exists for a session that held this task.
        # Minimal fallback: return 404 to let client restart process, or if any status.json exists under artifacts, return last state.
        # Here: return 404 to keep behavior predictable.
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "state": info.state,
        "stage": info.stage,
        "progress_pct": info.progress_pct,
        "error_code": info.error_code,
        "error_message": info.error_message,
    }


