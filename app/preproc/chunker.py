"""Chunking utilities for document nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List


@dataclass
class Node:
    """Represents a logical node extracted from a source document."""

    content: str
    node_type: str = "text"
    h_path: List[str] | None = None


@dataclass
class Chunk:
    """Represents the unit stored in OpenSearch."""

    content: str
    overlap: int
    h_path: List[str] | None = None


def chunk_nodes(nodes: Iterable[Node], target_size: int = 750, overlap: int = 80) -> Iterator[Chunk]:
    """Yield simple chunks without altering the content.

    The function iterates the provided nodes and emits ``Chunk`` objects with
    the original content.  It records the configured overlap so future
    iterations can refine the algorithm to perform sliding-window chunking
    anchored on semantic boundaries.
    """

    for node in nodes:
        yield Chunk(content=node.content, overlap=overlap, h_path=node.h_path)
