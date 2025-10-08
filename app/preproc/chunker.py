"""Chunking utilities for document nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List


@dataclass
class Node:
    """Represents a logical node extracted from a source document."""

    content: str
    node_type: str = "text"
    h_path: List[str] | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """Represents the unit stored in OpenSearch."""

    content: str
    overlap: int
    h_path: List[str] | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def chunk_nodes(nodes: Iterable[Node], target_size: int = 750, overlap: int = 80) -> Iterator[Chunk]:
    """Yield chunks approximating ``target_size`` tokens with ``overlap``.

    The implementation operates on whitespace-delimited tokens to keep the
    runtime lightweight.  It emits overlapping windows so downstream ranking or
    generation models have enough context when assembling answers.
    """

    target_size = max(target_size, 50)
    stride = max(target_size - overlap, 1)

    for node in nodes:
        tokens = node.content.split()
        if not tokens:
            continue
        if len(tokens) <= target_size:
            yield Chunk(content=node.content.strip(), overlap=overlap, h_path=node.h_path, metadata=dict(node.metadata, chunk_index=0))
            continue

        chunk_index = 0
        start = 0
        while start < len(tokens):
            end = min(start + target_size, len(tokens))
            window = tokens[start:end]
            content = " ".join(window).strip()
            if content:
                yield Chunk(
                    content=content,
                    overlap=overlap,
                    h_path=node.h_path,
                    metadata=dict(node.metadata, chunk_index=chunk_index, token_start=start, token_end=end),
                )
                chunk_index += 1
            if end == len(tokens):
                break
            start += stride
