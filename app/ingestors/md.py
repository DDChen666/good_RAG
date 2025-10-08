"""Markdown ingestion helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


def normalise_markdown(md_paths: Iterable[Path]) -> List[str]:
    """Read and normalise Markdown files.

    The normalisation logic is intentionally conservative; it simply reads
    the file contents and strips trailing whitespace lines.  Future work can
    introduce heading canonicalisation and table/code normalisation in line
    with the PRD.
    """

    documents: List[str] = []
    for path in md_paths:
        content = path.read_text(encoding="utf-8")
        documents.append("\n".join(line.rstrip() for line in content.splitlines()))
    return documents
