"""Client utilities for interacting with Ollama embeddings."""

from __future__ import annotations

import logging
from typing import Iterable, List
from urllib.parse import urljoin

import requests

from app.config import settings

LOGGER = logging.getLogger(__name__)


class EmbeddingClient:
    """Minimal HTTP client for the Ollama embeddings endpoint."""

    def __init__(self) -> None:
        self._endpoint = urljoin(str(settings.ollama_url), "/api/embeddings")

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        """Return embeddings for the supplied texts.

        The function submits one request per text to keep the implementation
        straightforward because most lighter-weight Ollama models expect a
        single prompt.  Errors are logged and result in empty vectors so callers
        can decide how to handle the failure.
        """

        vectors: List[List[float]] = []
        for text in texts:
            payload = {"model": settings.ollama_embed_model, "prompt": text}
            try:
                response = requests.post(self._endpoint, json=payload, timeout=settings.http_timeout)
                response.raise_for_status()
                data = response.json()
                vector = data.get("embedding")
                if vector is None and isinstance(data.get("data"), list):
                    vector = data["data"][0].get("embedding")
                if isinstance(vector, list):
                    vectors.append(vector)
                else:  # pragma: no cover - defensive branch
                    LOGGER.warning("Unexpected embedding payload: %s", data)
                    vectors.append([])
            except requests.RequestException as exc:
                LOGGER.error("Embedding request failed: %s", exc)
                vectors.append([])
        return vectors


embedding_client = EmbeddingClient()
