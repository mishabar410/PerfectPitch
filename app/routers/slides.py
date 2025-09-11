"""Slide content and rendering endpoints.

GET /slides/{session_id} returns parsed slide texts/notes.
POST /slides/{session_id}/render creates PNG images for slides and returns URLs.
"""

from typing import Any, Dict, List
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.paths import UPLOADS_DIR, ARTIFACTS_DIR
from app.services.pptx_parser import parse_pptx_metrics
from app.services.judge import review_deck_per_slide
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
    return {"slides": slides, "count": len(slides), "metrics": metrics}


@router.post("/slides/{session_id}/render")
def render_slides(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    ppt = _find_presentation(folder)
    if ppt is None:
        raise HTTPException(status_code=400, detail="Presentation not found")
    out_dir = ARTIFACTS_DIR / session_id / "slides"
    try:
        paths: List[Path] = render_pptx_to_images(ppt, out_dir)
    except RuntimeError as e:
        # LibreOffice or conversion not available; degrade gracefully to text-only slides
        return {"images": [], "count": 0, "warning": str(e)}
    urls = [f"/artifacts/{session_id}/slides/{p.name}" for p in paths]
    return {"images": urls, "count": len(urls)}


@router.post("/slides/{session_id}/review")
def review_slides(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    ppt = _find_presentation(folder)
    if ppt is None:
        raise HTTPException(status_code=400, detail="Presentation not found")
    import json
    meta = {}
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    slides, metrics = parse_pptx_metrics(ppt)
    reviewed = review_deck_per_slide(slides, metrics, meta)
    # persist
    out_dir = ARTIFACTS_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / "slides_review.json").write_text(json.dumps(reviewed, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return reviewed


