"""Render PPTX/PPTM to slide images.

Uses LibreOffice for conversion (PDF/PNG) and pdf2image (poppler) for PDF→PNG.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import List

from pdf2image import convert_from_path


def render_pptx_to_images(ppt_path: Path, out_dir: Path, dpi: int = 150) -> List[Path]:
    """Render presentation into PNG images.

    Returns list of image Paths in order. Raises if LibreOffice not found.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Convert PPTX using LibreOffice (soffice). Try PDF first, then PNG as fallback.
    soffice = _which_soffice()
    if soffice is None:
        raise RuntimeError("LibreOffice (soffice) not found. Please install LibreOffice and ensure 'soffice' is in PATH.")

    with tempfile.TemporaryDirectory() as tmpd:
        tmp_dir = Path(tmpd)

        # Try PDF conversion (two filter variants)
        pdf = _try_convert(soffice, ppt_path, tmp_dir, "pdf:impress_pdf_Export") or \
              _try_convert(soffice, ppt_path, tmp_dir, "pdf")

        if pdf and pdf.exists():
            images = convert_from_path(str(pdf), dpi=dpi)
            result_paths: List[Path] = []
            for i, img in enumerate(images, start=1):
                p = out_dir / f"slide-{i:03d}.png"
                img.save(str(p), format="PNG")
                result_paths.append(p)
            if result_paths:
                return result_paths

        # Fallback: try direct PNG export
        _ = _run_soffice(soffice, [
            "--headless", "--convert-to", "png:impress_png_Export", "--outdir", str(tmp_dir), str(ppt_path)
        ])
        pngs = sorted(tmp_dir.glob("*.png"))
        if not pngs:
            # last resort without explicit filter
            _ = _run_soffice(soffice, [
                "--headless", "--convert-to", "png", "--outdir", str(tmp_dir), str(ppt_path)
            ])
            pngs = sorted(tmp_dir.glob("*.png"))
        if pngs:
            result_paths: List[Path] = []
            for i, src in enumerate(pngs, start=1):
                dst = out_dir / f"slide-{i:03d}.png"
                dst.write_bytes(src.read_bytes())
                result_paths.append(dst)
            return result_paths

        raise RuntimeError("LibreOffice conversion failed: no PDF or PNG produced. Ensure LibreOffice can open the file.")


def _which_soffice() -> str | None:
    import shutil

    for name in ["soffice", "libreoffice"]:
        p = shutil.which(name)
        if p:
            return p
    return None


def _try_convert(soffice: str, src: Path, outdir: Path, convert_to: str) -> Path | None:
    _ = _run_soffice(soffice, [
        "--headless", "--convert-to", convert_to, "--outdir", str(outdir), str(src)
    ])
    # find first matching output
    if convert_to.startswith("pdf"):
        pdfs = list(outdir.glob("*.pdf"))
        return pdfs[0] if pdfs else None
    return None


def _run_soffice(soffice: str, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run([soffice, *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


