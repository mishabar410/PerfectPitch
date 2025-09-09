"""Text analysis endpoints.

POST /text/{session_id}/analyze — analyze uploaded script with GPT given meta.
"""

from typing import Any, Dict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.paths import UPLOADS_DIR, ARTIFACTS_DIR
from app.services.doc_parser import parse_word_script
from app.services.judge import analyze_script_with_meta


router = APIRouter()


def _load_meta(folder: Path) -> Dict[str, Any]:
    import json
    p = folder / "meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _load_script_text(folder: Path) -> str:
    txt_path = folder / "script.txt"
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8")
    # try word
    for name in ["word.docx", "word.docm", "script.docx", "script.docm", "word.doc"]:
        p = folder / name
        if p.exists():
            try:
                parsed = parse_word_script(p)
                return parsed.get("text", "")
            except Exception:
                break
    return ""


@router.post("/text/{session_id}/analyze")
def analyze_text(session_id: str) -> Dict[str, Any]:
    folder = UPLOADS_DIR / session_id
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    script_text = _load_script_text(folder)
    if not script_text:
        raise HTTPException(status_code=400, detail="Script text not found. Upload script.txt or Word file.")

    meta = _load_meta(folder)
    result = analyze_script_with_meta(script_text, meta)

    # persist partial artifacts for UI reuse
    out_dir = ARTIFACTS_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import json
        (out_dir / "text_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result


