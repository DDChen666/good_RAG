"""Utilities for interacting with OpenSearch.

The functions defined here avoid binding the rest of the application to a
specific client implementation.  They use the OpenSearch REST API via
``requests`` so the module stays lightweight and works even when the
Python ``opensearch-py`` package is unavailable in the execution
environment.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests

from app.config import settings

LOGGER = logging.getLogger(__name__)


class OpenSearchClient:
    """A minimal OpenSearch helper focused on index bootstrap and search."""

    def __init__(self) -> None:
        self._detected_dims: Optional[int] = None

    @property
    def detected_dims(self) -> int:
        """Return the embedding dimensionality detected from Ollama."""

        if self._detected_dims is None:
            self._detected_dims = self._detect_embedding_dims()
        return self._detected_dims

    def _detect_embedding_dims(self) -> int:
        url = urljoin(str(settings.ollama_url), "/api/embeddings")
        payload = {"model": settings.ollama_embed_model, "prompt": "ping"}
        try:
            response = requests.post(url, json=payload, timeout=settings.http_timeout)
            response.raise_for_status()
            data = response.json()
            vector = data.get("embedding")
            if vector is None and isinstance(data.get("data"), list):
                first = data["data"][0]
                vector = first.get("embedding")
            if isinstance(vector, list) and vector:
                return len(vector)
        except requests.RequestException as exc:
            LOGGER.warning("Falling back to default embedding dims: %s", exc)
        return settings.default_embedding_dims

    def ensure_index(self) -> None:
        """Create the OpenSearch index if it does not already exist."""

        index_url = urljoin(str(settings.os_url), f"/{settings.index_name}")
        try:
            response = requests.head(index_url, timeout=settings.http_timeout)
            if response.status_code == 404:
                mapping = self._build_mapping()
                create = requests.put(
                    index_url,
                    data=json.dumps(mapping),
                    headers={"Content-Type": "application/json"},
                    timeout=settings.http_timeout,
                )
                create.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Unable to verify OpenSearch index: %s", exc)

    def _build_mapping(self) -> Dict[str, Any]:
        dims = self.detected_dims
        return {
            "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
            "mappings": {
                "properties": {
                    "content": {"type": "text"},
                    "content_vector": {
                        "type": "dense_vector",
                        "dims": dims,
                        "index": True,
                        "similarity": "cosine",
                    },
                    "node_type": {"type": "keyword"},
                    "code_lang": {"type": "keyword"},
                    "endpoint": {"type": "keyword"},
                    "http_method": {"type": "keyword"},
                    "param_names": {"type": "keyword"},
                    "error_codes": {"type": "keyword"},
                    "h_path": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "url": {"type": "keyword"},
                    "anchor": {"type": "keyword"},
                    "version": {"type": "keyword"},
                    "last_seen_at": {"type": "date"},
                    "doc_key": {"type": "keyword"},
                    "content_hash": {"type": "keyword"},
                }
            },
        }

    def bulk_index(self, chunks: Iterable[Dict[str, Any]]) -> None:
        """Index a batch of chunk documents via the OpenSearch bulk API."""

        bulk_endpoint = urljoin(str(settings.os_url), f"/{settings.index_name}/_bulk")
        lines: List[str] = []
        for chunk in chunks:
            action = {"index": {"_index": settings.index_name, "_id": chunk["doc_key"]}}
            lines.append(json.dumps(action))
            lines.append(json.dumps(chunk))
        if not lines:
            return
        payload = "\n".join(lines) + "\n"
        response = requests.post(
            bulk_endpoint,
            data=payload,
            headers={"Content-Type": "application/x-ndjson"},
            timeout=settings.http_timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            LOGGER.error("Bulk indexing reported errors: %s", data)

    def hybrid_search(self, query: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build a hybrid query request body for inspection or execution."""

        if filters is None:
            filters = {}
        should_filters: List[Dict[str, Any]] = []
        if domain := filters.get("domain"):
            should_filters.append({"term": {"source": domain}})
        if version := filters.get("version"):
            should_filters.append({"term": {"version": version}})
        query_body = {
            "size": max(settings.bm25_top_n, settings.vector_top_n),
            "query": {
                "bool": {
                    "should": [
                        {"match": {"content": query}},
                        {
                            "script_score": {
                                "query": {"match_all": {}},
                                "script": {
                                    "source": "cosineSimilarity(params.query_vector, 'content_vector') + 1.0",
                                    "params": {"query_vector": []},
                                },
                            }
                        },
                    ],
                    "filter": should_filters,
                }
            },
        }
        return query_body


client = OpenSearchClient()
