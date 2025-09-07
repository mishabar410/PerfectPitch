"""Utilities to parse speech script from Word documents.

Supports .docx/.docm via python-docx; for legacy .doc, return a basic notice.
"""

from pathlib import Path
from typing import Dict, Any

from docx import Document  # type: ignore


def parse_word_script(path: Path) -> Dict[str, Any]:
    """Extract plain text paragraphs from a Word document.

    Returns {"text": str, "paragraphs": [str], "meta": {...}}.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() in {".docx", ".docm"}:
        doc = Document(str(path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        text = "\n".join(paragraphs)
        meta = {"paragraph_count": len(paragraphs)}
        return {"text": text, "paragraphs": paragraphs, "meta": meta}
    # For .doc or others: no parsing in MVP
    return {"text": "", "paragraphs": [], "meta": {"note": "Unsupported format for parsing in MVP"}}


