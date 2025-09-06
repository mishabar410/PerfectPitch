"""Slide content and rendering endpoints.

GET /slides/{session_id} returns parsed slide texts/notes.
POST /slides/{session_id}/render creates PNG images for slides and returns URLs.
"""

from typing import Any, Dict, List
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.paths import UPLOADS_DIR, ARTIFACTS_DIR
from app.services.pptx_parser import parse_pptx_metrics
from app.services.pptx_render import render_pptx_to_images


router = APIRouter()


def _find_presentation(folder: Path) -> Path | None:
    for name in ["pptx.pptm", "pptx.pptx", "presentation.pptx"]:
        p = folder / name
        if p.exists():
            return p
    return None


@router.get("/slides/{session_id}")
def get_slides(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    ppt = _find_presentation(folder)
    if ppt is None:
        raise HTTPException(status_code=400, detail="Presentation not found")
    slides, metrics = parse_pptx_metrics(ppt)
    return {"slides": slides, "count": len(slides)}


@router.post("/slides/{session_id}/render")
def render_slides(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    ppt = _find_presentation(folder)
    if ppt is None:
        raise HTTPException(status_code=400, detail="Presentation not found")
    out_dir = ARTIFACTS_DIR / session_id / "slides"
    paths: List[Path] = render_pptx_to_images(ppt, out_dir)
    urls = [f"/artifacts/{session_id}/slides/{p.name}" for p in paths]
    return {"images": urls, "count": len(urls)}


