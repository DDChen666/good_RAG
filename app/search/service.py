"""High level search orchestration utilities."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.search.hybrid import build_answer_context, reciprocal_rank_fusion
from app.search.opensearch_client import client

LOGGER = logging.getLogger(__name__)


class SearchService:
    """Perform hybrid retrieval and response shaping."""

    def __init__(self) -> None:
        try:
            client.ensure_index()
        except Exception:  # pragma: no cover - defensive guard for optional deps
            LOGGER.warning("OpenSearch index bootstrap skipped due to connection issues.")

    def query(self, query: str, domain_filter: Optional[List[str]] = None, version: Optional[str] = None) -> Dict[str, Any]:
        """Return a placeholder answer payload.

        The implementation currently builds the hybrid search request body and
        returns it alongside synthetic citations so API consumers can inspect
        the structure.  Retrieval integration can be added by extending this
        method to execute the generated query using OpenSearch's REST API and
        optionally calling a generation model.
        """

        filters: Dict[str, Any] = {}
        if domain_filter:
            filters["domain"] = domain_filter[0]
        if version:
            filters["version"] = version
        query_body = client.hybrid_search(query=query, filters=filters)
        LOGGER.debug("Hybrid query body: %s", query_body)
        mock_hit = {
            "id": "demo-doc",
            "title": "Placeholder citation",
            "url": "https://example.com/docs",
            "snippet": "Hybrid search body prepared; connect OpenSearch to enable retrieval.",
            "h_path": ["API Reference"],
        }
        fused = reciprocal_rank_fusion([[mock_hit]], k=settings.rrf_k)
        context = build_answer_context(fused[: settings.query_top_k])
        return {
            "answer": "Hybrid retrieval pipeline initialised. Connect OpenSearch to return live results.",
            "citations": context,
            "diagnostics": {"retrieval_ms": 0, "fusion_ms": 0, "total_ms": 0, "query_body": query_body},
        }


search_service = SearchService()
