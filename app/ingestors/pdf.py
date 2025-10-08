"""PDF ingestion pipeline components."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List

from pypdf import PdfReader

LOGGER = logging.getLogger(__name__)


def extract_text(pdf_paths: Iterable[Path]) -> List[str]:
    """Extract plain text from the provided PDF files.

    ``pypdf`` is used for its pure-Python implementation so the ingestion can
    run inside the container without extra system libraries.  Each element in
    the returned list corresponds to the respective ``pdf_paths`` entry.  When a
    file cannot be parsed the function logs the error and returns an empty
    string placeholder so the caller can surface the failure in the job status.
    """

    texts: List[str] = []
    for path in pdf_paths:
        try:
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(pages).strip()
            texts.append(text)
        except Exception as exc:  # pragma: no cover - depends on input PDFs
            LOGGER.warning("Failed to extract PDF %s: %s", path, exc)
            texts.append("")
    return texts
