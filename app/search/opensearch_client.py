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
import base64
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
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "knn": True,
                }
            },
            "mappings": {
                "properties": {
                    "content": {"type": "text"},
                    "content_vector": {
                        "type": "knn_vector",
                        "dimension": dims,
                        "method": {
                            "name": "hnsw",
                            "engine": "nmslib",
                            "space_type": "cosinesimil",
                        },
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

    def hybrid_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        query_vector: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Return payloads suitable for BM25 and k-NN searches."""

        filters = filters or {}
        should_filters: List[Dict[str, Any]] = []
        if domain := filters.get("domain"):
            if isinstance(domain, list):
                should_filters.append({"terms": {"source": domain}})
            else:
                should_filters.append({"term": {"source": domain}})
        if version := filters.get("version"):
            if isinstance(version, list):
                should_filters.append({"terms": {"version": version}})
            else:
                should_filters.append({"term": {"version": version}})
        text_query = {
            "size": settings.bm25_top_n,
            "query": {
                "bool": {
                    "must": {"match": {"content": query}},
                    **({"filter": should_filters} if should_filters else {}),
                }
            },
        }
        knn_body: Optional[Dict[str, Any]] = None
        if query_vector:
            knn_body = {
                "knn": {
                    "field": "content_vector",
                    "query_vector": query_vector,
                    "k": settings.vector_top_n,
                    "num_candidates": max(settings.vector_top_n * 2, 50),
                }
            }
            if should_filters:
                knn_body["filter"] = {"bool": {"filter": should_filters}}
        return {"text": text_query, "knn": knn_body}

    def search(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a search request against the configured index."""

        search_endpoint = urljoin(str(settings.os_url), f"/{settings.index_name}/_search")
        response = requests.post(
            search_endpoint,
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=settings.http_timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            LOGGER.error("OpenSearch _search failed: %s -- payload=%s -- response=%s", exc, body, response.text)
            raise
        return response.json()

    def knn_search(
        self,
        query_vector: List[float],
        k: int,
        filter_clauses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute a k-NN search using the OpenSearch _knn_search API."""

        if not query_vector:
            return {}
        endpoint = urljoin(str(settings.os_url), f"/{settings.index_name}/_search")
        body: Dict[str, Any] = {
            "size": max(k, 1),
            "query": {
                "knn": {
                    "content_vector": {
                        "vector": query_vector,
                        "k": max(k, 1),
                        "num_candidates": max(k * 2, 50),
                    }
                }
            },
        }
        if filter_clauses:
            filter_query: Dict[str, Any]
            if len(filter_clauses) == 1:
                filter_query = filter_clauses[0]
            else:
                filter_query = {"bool": {"filter": filter_clauses}}
            body["query"]["knn"]["content_vector"]["filter"] = filter_query

        response = requests.post(
            endpoint,
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=settings.http_timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            LOGGER.error("OpenSearch _knn_search failed: %s -- payload=%s -- response=%s", exc, body, response.text)
            raise
        return response.json()

    @staticmethod
    def encode_source_id(value: str) -> str:
        """Return a URL-safe identifier for a given source name."""

        raw = value.encode("utf-8")
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return token

    @staticmethod
    def decode_source_id(token: str) -> str:
        """Decode a URL-safe identifier back into the original source name."""

        if not token:
            raise ValueError("Source identifier cannot be empty.")
        padding = "=" * (-len(token) % 4)
        try:
            raw = base64.urlsafe_b64decode(token + padding)
        except (base64.binascii.Error, ValueError) as exc:
            raise ValueError("Invalid source identifier.") from exc
        return raw.decode("utf-8")

    def list_sources(self, size: int = 500) -> List[Dict[str, Any]]:
        """Return aggregated document counts per source."""

        search_endpoint = urljoin(str(settings.os_url), f"/{settings.index_name}/_search")
        body = {
            "size": 0,
            "aggs": {
                "by_source": {
                    "terms": {
                        "field": "source",
                        "size": size,
                        "order": {"_key": "asc"},
                    }
                }
            },
        }
        try:
            response = requests.post(
                search_endpoint,
                data=json.dumps(body),
                headers={"Content-Type": "application/json"},
                timeout=settings.http_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Failed to list sources: %s", exc)
            return []

        buckets = response.json().get("aggregations", {}).get("by_source", {}).get("buckets", [])
        sources: List[Dict[str, Any]] = []
        for bucket in buckets:
            key = bucket.get("key")
            if not key:
                continue
            doc_count = int(bucket.get("doc_count", 0))
            sources.append(
                {
                    "id": self.encode_source_id(str(key)),
                    "name": str(key),
                    "document_count": doc_count,
                }
            )
        return sources

    def delete_source(self, source_name: str) -> int:
        """Delete all documents that belong to the given source. Returns the deleted count."""

        delete_endpoint = urljoin(str(settings.os_url), f"/{settings.index_name}/_delete_by_query")
        body = {"query": {"term": {"source": source_name}}}
        try:
            response = requests.post(
                delete_endpoint,
                data=json.dumps(body),
                headers={"Content-Type": "application/json"},
                timeout=settings.http_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.error("Failed to delete source '%s': %s", source_name, exc)
            raise

        payload = response.json()
        return int(payload.get("deleted", 0))


client = OpenSearchClient()
