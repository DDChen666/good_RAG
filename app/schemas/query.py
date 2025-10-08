"""Query request/response models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class Citation(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    h_path: Optional[List[str]] = None
    siblings: Optional[List[str]] = None


class QueryDiagnostics(BaseModel):
    embedding_ms: Optional[int] = None
    retrieval_ms: int
    rerank_ms: Optional[int] = None
    fusion_ms: int
    total_ms: int
    query_body: dict


class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    diagnostics: QueryDiagnostics


class QueryRequest(BaseModel):
    q: str
    top_k: Optional[int] = None
    domain_filter: Optional[List[str]] = None
    version: Optional[str] = None
