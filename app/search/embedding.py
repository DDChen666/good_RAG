"""Embedding utilities with OpenSearch ML Commons integration."""

from __future__ import annotations

import contextlib
import logging
from typing import Iterable, List, Optional
from urllib.parse import urljoin

import requests

from app.config import settings
from app.search.ml_commons import MLCommonsError, RemoteModelManager

LOGGER = logging.getLogger(__name__)


class _DirectOllamaClient:
    """Direct HTTP client that talks to Ollama's embedding API."""

    def __init__(self) -> None:
        base_url = str(settings.ollama_url)
        self._candidate_endpoints = [
            urljoin(base_url, "/api/embeddings"),
            urljoin(base_url, "/api/embed"),
        ]
        self._active_endpoint: Optional[str] = None
        self._model_checked = False
        self._pull_endpoint = urljoin(base_url, "/api/pull")
        self._show_endpoint = urljoin(base_url, "/api/show")

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        self._ensure_model_available()
        for text in texts:
            vector = self._fetch_embedding(text)
            vectors.append(vector if vector is not None else [])
        return vectors

    def _ensure_model_available(self, force: bool = False) -> bool:
        if self._model_checked and not force:
            return True

        payload = {"name": settings.ollama_embed_model}
        try:
            response = requests.post(self._show_endpoint, json=payload, timeout=settings.http_timeout)
            if response.status_code == 404:
                LOGGER.info("Embedding model '%s' missing; attempting to pull.", settings.ollama_embed_model)
                pulled = self._pull_model()
                self._model_checked = pulled
                return pulled
            response.raise_for_status()
            self._model_checked = True
            return True
        except requests.RequestException as exc:
            LOGGER.warning("Unable to verify Ollama model '%s': %s", settings.ollama_embed_model, exc)
            self._model_checked = False
            return False

    def _pull_model(self) -> bool:
        try:
            with requests.post(
                self._pull_endpoint,
                json={"name": settings.ollama_embed_model},
                stream=True,
                timeout=max(settings.http_timeout, 300),
            ) as response:
                response.raise_for_status()
                for _ in response.iter_lines():
                    pass
            LOGGER.info("Successfully pulled embedding model '%s'.", settings.ollama_embed_model)
            return True
        except requests.RequestException as exc:
            LOGGER.error("Failed to pull embedding model '%s': %s", settings.ollama_embed_model, exc)
            return False

    def _fetch_embedding(self, text: str) -> Optional[List[float]]:
        endpoints = [self._active_endpoint] if self._active_endpoint else list(self._candidate_endpoints)
        for endpoint in filter(None, endpoints):
            try:
                vector = self._post_embedding(endpoint, text)
                if vector is not None:
                    self._active_endpoint = endpoint
                    return vector
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    if endpoint == self._active_endpoint:
                        self._active_endpoint = None
                    continue
                LOGGER.error("Embedding request failed: %s", exc)
                break
            except requests.RequestException as exc:
                LOGGER.error("Embedding request failed: %s", exc)
                break
        return None

    def _post_embedding(self, endpoint: str, text: str, retry: bool = True) -> Optional[List[float]]:
        payload = {"model": settings.ollama_embed_model, "prompt": text}
        response = requests.post(endpoint, json=payload, timeout=settings.http_timeout)

        if response.status_code == 404:
            response.raise_for_status()

        if response.status_code == 400 and retry:
            error_message = ""
            with contextlib.suppress(ValueError):
                data = response.json()
                error_message = data.get("error", "")
            if "model" in error_message and "not found" in error_message.lower():
                if self._ensure_model_available(force=True):
                    return self._post_embedding(endpoint, text, retry=False)

        response.raise_for_status()
        data = response.json()
        vector = data.get("embedding")
        if vector is None and isinstance(data.get("data"), list):
            vector = data["data"][0].get("embedding")
        if isinstance(vector, list):
            return vector
        LOGGER.warning("Unexpected embedding payload: %s", data)
        return None


class EmbeddingClient:
    """High-level embedding client with ML Commons fallback."""

    def __init__(self) -> None:
        self._remote_manager = RemoteModelManager() if settings.use_ml_commons_remote_embeddings else None
        self._direct_client = _DirectOllamaClient()

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        payload = [text for text in texts]
        if not payload:
            return []

        if self._remote_manager is not None:
            try:
                vectors = self._remote_manager.infer_embeddings(payload)
                if vectors:
                    return vectors
            except MLCommonsError as exc:
                LOGGER.warning("OpenSearch ML Commons remote embedding failed: %s", exc)

        LOGGER.debug("Falling back to direct Ollama embedding client.")
        return self._direct_client.embed(payload)


embedding_client = EmbeddingClient()
