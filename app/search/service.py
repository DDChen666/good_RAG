"""High level search orchestration utilities."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from app.config import settings
from app.search.embedding import embedding_client
from app.search.generation import generate_answer
from app.search.hybrid import build_answer_context, reciprocal_rank_fusion
from app.search.opensearch_client import client

LOGGER = logging.getLogger(__name__)


def _build_filter_clauses(domain_filter: Optional[List[str]], version: Optional[str]) -> List[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = []
    if domain_filter:
        clauses.append({"terms": {"source": domain_filter}})
    if version:
        clauses.append({"term": {"version": version}})
    return clauses


def _normalise_hits(raw_hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for rank, hit in enumerate(raw_hits, start=1):
        source = hit.get("_source", {})
        content = source.get("content", "")
        snippet = content[:400] + ("…" if len(content) > 400 else "")
        hits.append(
            {
                "id": source.get("doc_key", hit.get("_id")),
                "title": source.get("h_path", [source.get("source", "Document")])[-1] if source.get("h_path") else source.get("source", "Document"),
                "url": source.get("url"),
                "snippet": snippet,
                "content": content,
                "score": hit.get("_score"),
                "rank": rank,
                "source": source.get("source"),
                "version": source.get("version"),
                "h_path": source.get("h_path", []),
                "vector": source.get("content_vector"),
            }
        )
    return hits


class SearchService:
    """Perform hybrid retrieval and response shaping."""

    def __init__(self) -> None:
        try:
            client.ensure_index()
        except Exception:  # pragma: no cover - defensive guard for optional deps
            LOGGER.warning("OpenSearch index bootstrap skipped due to connection issues.")

    def query(self, query: str, domain_filter: Optional[List[str]] = None, version: Optional[str] = None) -> Dict[str, Any]:
        start_total = time.perf_counter()
        filter_clauses = _build_filter_clauses(domain_filter, version)

        # Generate query embedding
        embed_start = time.perf_counter()
        query_vectors = embedding_client.embed([query])
        query_vector = query_vectors[0] if query_vectors else []
        embed_ms = int((time.perf_counter() - embed_start) * 1000)

        bool_filter = {"filter": filter_clauses} if filter_clauses else {}

        text_query = {
            "size": settings.bm25_top_n,
            "query": {
                "bool": {
                    **bool_filter,
                    "must": {"match": {"content": query}},
                }
            },
        }

        retrieval_start = time.perf_counter()
        bm25_response = client.search(text_query)
        retrieval_ms = int((time.perf_counter() - retrieval_start) * 1000)

        bm25_hits = _normalise_hits(bm25_response.get("hits", {}).get("hits", []))
        vector_hits: List[Dict[str, Any]] = []
        vector_ms = 0
        vector_error: Optional[str] = None
        if query_vector:
            vector_start = time.perf_counter()
            try:
                knn_response = client.knn_search(
                    query_vector,
                    settings.vector_top_n,
                    filter_clauses,
                )
                vector_hits = _normalise_hits(knn_response.get("hits", {}).get("hits", []))
            except requests.HTTPError as exc:
                vector_error = f"HTTP {exc.response.status_code} {exc.response.reason if exc.response else ''}".strip()
                LOGGER.warning("k-NN search failed with HTTP error: %s", exc)
            except requests.RequestException as exc:
                vector_error = str(exc)
                LOGGER.warning("k-NN search failed: %s", exc)
            finally:
                vector_ms = int((time.perf_counter() - vector_start) * 1000)

        fused = reciprocal_rank_fusion([bm25_hits, vector_hits], k=settings.rrf_k)
        top_hits = fused[: settings.query_top_k]
        context = build_answer_context(top_hits)
        for item in context:
            item.pop("vector", None)

        answer = generate_answer(query, context)

        total_ms = int((time.perf_counter() - start_total) * 1000)
        diagnostics = {
            "embedding_ms": embed_ms,
            "retrieval_ms": retrieval_ms,
            "vector_ms": vector_ms,
            "rerank_ms": vector_ms,
            "total_ms": total_ms,
            "bm25_query": text_query,
            "bm25_hits": len(bm25_hits),
            "vector_hits": len(vector_hits),
            "fusion_ms": vector_ms,
            "query_body": {
                "text": text_query,
                "knn": {
                    "content_vector": {
                        "vector": query_vector,
                        "k": settings.vector_top_n,
                        "num_candidates": max(settings.vector_top_n * 2, 50),
                        **(
                            {"filter": {"bool": {"filter": filter_clauses}}}
                            if filter_clauses
                            else {}
                        ),
                    }
                }
                if query_vector
                else None,
            },
        }
        if vector_error:
            diagnostics["vector_error"] = vector_error
        if not query_vector:
            diagnostics["query_body"].pop("knn", None)
        if settings.gemini_api_key:
            diagnostics["llm_model"] = settings.gemini_model

        return {
            "answer": answer,
            "citations": context,
            "diagnostics": diagnostics,
        }


search_service = SearchService()
