"""PDF ingestion pipeline components."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


def extract_text(pdf_paths: Iterable[Path]) -> List[str]:
    """Placeholder PDF extractor.

    The production version should rely on libraries such as PyMuPDF or
    pdfplumber.  This stub returns simple marker strings so that unit tests can
    be written without external dependencies.
    """

    return [f"<pdf:{path.name}>" for path in pdf_paths]
