"""
File conversion utilities for Bot-File-School.
- images -> single PDF  (Pillow)
- .docx -> PDF          (LibreOffice headless, best effort)
- .pdf  -> .docx        (PyMuPDF extracts text into a Word doc)
All conversions work fully inside the bot's workspace - files are never
sent to any external service.
"""

import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List

from logger import logger

TEMP_DIR = Path(tempfile.gettempdir()) / "bfs_convert"


def _ensure_temp() -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR


def images_to_pdf(image_paths: List[Path], out_path: Path) -> Path:
    """Convert a list of image files into one PDF using Pillow."""
    from PIL import Image

    out_path.parent.mkdir(parents=True, exist_ok=True)
    imgs: List[Image.Image] = []
    try:
        for p in image_paths:
            img = Image.open(p)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            imgs.append(img)
        if not imgs:
            raise ValueError("No images received")
        first, rest = imgs[0], imgs[1:]
        first.save(out_path, "PDF", save_all=True, append_images=rest)
    finally:
        for img in imgs:
            try:
                img.close()
            except Exception:
                pass
    return out_path


def _libreoffice_bin() -> str | None:
    """Locate the LibreOffice / soffice binary cross-platform."""
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        for cand in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(cand).exists():
                return cand
    return None


def word_to_pdf(docx_path: Path, out_dir: Path) -> Path:
    """Convert a .docx to PDF via LibreOffice headless (best effort)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    soffice = _libreoffice_bin()
    if not soffice:
        raise RuntimeError(
            "LibreOffice پیدا نشد. برای تبدیل Word→PDF📊 LibreOffice یا MS Word "
            "را نصب کنید (پس از نصب ربات را ری‌استارت کنید)."
        )
    cmd = [
        soffice, "--headless", "--norestore", "--convert-to", "pdf",
        "--outdir", str(out_dir), str(docx_path),
    ]
    logger.info(f"Running LibreOffice: {' '.join(cmd)}")
    subprocess.run(cmd, timeout=60, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out_pdf = out_dir / (docx_path.stem + ".pdf")
    if not out_pdf.exists():
        raise RuntimeError("تبدیل Word→PDF انجام نشد (خروجی تولید نشد).")
    return out_pdf


def pdf_to_word(pdf_path: Path, out_path: Path) -> Path:
    """Extract text from PDF pages and build a .docx with python-docx."""
    import fitz  # PyMuPDF
    from docx import Document
    from docx.shared import Pt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    with fitz.open(pdf_path) as pdf:
        for i, page in enumerate(pdf, start=1):
            doc.add_heading(f"صفحه {i}", level=2)
            text = page.get_text("text").strip()
            if text:
                for line in text.splitlines():
                    p = doc.add_paragraph(line)
                    p.runs and getattr(p.runs[0], "font", None)
            else:
                doc.add_paragraph("(متن قابل استخراج نبود - احتملاً تصویر/اسکن است)")
    doc.save(out_path)
    return out_path


def safe_name(name: str, default: str = "converted") -> str:
    """Sanitize a user-provided file name."""
    name = (name or "").strip()
    banned = '<>:"/\\|?*\n\r\t'
    cleaned = "".join(c for c in name if c not in banned).strip(". ")
    return cleaned[:120] or default
