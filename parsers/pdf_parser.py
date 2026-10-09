"""PDF text extraction without OCR."""

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(frozen=True)
class PDFResult:
    text: str
    needs_ocr: bool


def parse_pdf(path: Path) -> PDFResult:
    with fitz.open(path) as document:
        text = "\n".join(page.get_text("text") for page in document).strip()
    return PDFResult(text=text, needs_ocr=len(text) < 30)
