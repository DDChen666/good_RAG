"""Helpers for interacting with OpenSearch ML Commons remote models."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from app.config import settings

LOGGER = logging.getLogger(__name__)


class MLCommonsError(RuntimeError):
    """Raised when ML Commons operations fail."""


class RemoteModelManager:
    """Best-effort helper that wires OpenSearch remote models to Ollama."""

    def __init__(self) -> None:
        self._base_url = str(settings.os_url)
        self._timeout = settings.http_timeout
        self._connector_name = f"ollama-{settings.ollama_embed_model}-connector"
        self._model_name = f"ollama-{settings.ollama_embed_model}-remote"
        self._connector_id: Optional[str] = None
        self._model_id: Optional[str] = None

    def ensure_remote_model(self) -> str:
        """Return an active remote model id, creating resources if required."""

        if self._model_id:
            return self._model_id

        connector_id = self._ensure_connector()
        model = self._find_model()
        if model is None:
            self._model_id = self._register_model(connector_id)
        else:
            self._model_id = model["model_id"]
            if model.get("deploy_status", "").lower() != "deployed":
                self._deploy_model(self._model_id)
        return self._model_id

    def infer_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Run inference through ML Commons for the supplied texts."""

        if not texts:
            return []

        model_id = self.ensure_remote_model()
        infer_url = urljoin(self._base_url, "/_plugins/_ml/_infer")
        body = {
            "model_id": model_id,
            "task_type": "text_embedding",
            "text_docs": texts,
        }
        response = requests.post(infer_url, json=body, timeout=max(self._timeout, 30.0))
        if response.status_code == 404:
            raise MLCommonsError("ML Commons inference endpoint unavailable.")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MLCommonsError(f"Failed to infer embeddings: {exc}") from exc

        data = response.json()
        vectors: List[List[float]] = []
        if isinstance(data.get("inference_results"), list):
            for item in data["inference_results"]:
                vector = self._extract_vector(item)
                vectors.append(vector)
        elif isinstance(data.get("text_embedding_results"), list):
            for item in data["text_embedding_results"]:
                vector = self._extract_vector(item)
                vectors.append(vector)
        elif isinstance(data.get("text_embedding"), list):
            for vector in data["text_embedding"]:
                vectors.append(self._normalise_vector(vector))
        else:
            raise MLCommonsError(f"Unexpected ML Commons response format: {data}")

        return vectors

    def _ensure_connector(self) -> str:
        if self._connector_id:
            return self._connector_id

        existing = self._find_connector()
        if existing:
            self._connector_id = existing
            return existing

        create_url = urljoin(self._base_url, "/_plugins/_ml/connectors/_create")
        payload = {
            "name": self._connector_name,
            "description": "HTTP connector that relays embedding requests to Ollama.",
            "connector": {
                "transport": {
                    "type": "http",
                    "parameters": {
                        "endpoint": str(settings.ollama_url).rstrip("/"),
                        "method": "POST",
                        "path": "/api/embeddings",
                        "headers": {"Content-Type": "application/json"},
                        "client_request_timeout": int(max(self._timeout, 30.0) * 1000),
                    },
                    "request_body": '{"model":"%s","prompt":"${parameters.prompt}"}' % settings.ollama_embed_model,
                },
                "credential": {"type": "noauth"},
                "parameters": {"prompt": "${input.text}"},
                "actions": [
                    {
                        "action_type": "predict",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                        "url": str(settings.ollama_url).rstrip("/") + "/api/embeddings",
                        "request_body": '{"model":"%s","prompt":"${parameters.prompt}"}' % settings.ollama_embed_model,
                        "response_parse_field": "embedding",
                    }
                ],
            },
        }

        response = requests.post(create_url, json=payload, timeout=max(self._timeout, 30.0))
        if response.status_code == 409:
            connector_id = self._find_connector()
            if connector_id:
                self._connector_id = connector_id
                return connector_id
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MLCommonsError(f"Failed to create connector: {exc}") from exc

        data = response.json()
        connector_id = data.get("connector_id") or data.get("data", {}).get("connector_id")
        if not connector_id:
            raise MLCommonsError(f"Connector creation returned unexpected payload: {data}")
        self._connector_id = connector_id
        return connector_id

    def _find_connector(self) -> Optional[str]:
        search_url = urljoin(self._base_url, "/_plugins/_ml/connectors/_search")
        body = {
            "query": {
                "match": {
                    "name": self._connector_name,
                }
            },
            "size": 1,
        }
        try:
            response = requests.post(search_url, json=body, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None
        data = response.json()
        connectors = data.get("connectors") or data.get("data")
        if isinstance(connectors, list) and connectors:
            connector = connectors[0]
            return connector.get("connector_id") or connector.get("id")
        return None

    def _find_model(self) -> Optional[Dict[str, Any]]:
        search_url = urljoin(self._base_url, "/_plugins/_ml/models/_search")
        body = {
            "size": 1,
            "query": {
                "term": {
                    "name.keyword": self._model_name,
                }
            },
        }
        try:
            response = requests.post(search_url, json=body, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None
        data = response.json()
        models = data.get("models") or data.get("data")
        if isinstance(models, list) and models:
            return models[0]
        return None

    def _register_model(self, connector_id: str) -> str:
        register_url = urljoin(self._base_url, "/_plugins/_ml/models/_register")
        payload = {
            "name": self._model_name,
            "description": f"Ollama remote embedding model ({settings.ollama_embed_model})",
            "connector_id": connector_id,
            "model_format": "CUSTOM",
            "function_name": "remote",
            "parameters": {
                "prompt": "${input.text}",
            },
        }
        response = requests.post(register_url, json=payload, timeout=max(self._timeout, 30.0))
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MLCommonsError(f"Failed to register remote model: {exc}") from exc

        data = response.json()
        task_id = data.get("task_id")
        if not task_id:
            raise MLCommonsError(f"Remote model registration returned unexpected payload: {data}")
        model_id = self._wait_for_task(task_id)
        self._deploy_model(model_id)
        return model_id

    def _deploy_model(self, model_id: str) -> None:
        deploy_url = urljoin(self._base_url, f"/_plugins/_ml/models/{model_id}/_deploy")
        response = requests.post(deploy_url, timeout=max(self._timeout, 30.0))
        if response.status_code == 409:
            return
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MLCommonsError(f"Failed to deploy remote model '{model_id}': {exc}") from exc

        payload = response.json()
        task_id = payload.get("task_id")
        if task_id:
            self._wait_for_task(task_id, timeout=180)

    def _wait_for_task(self, task_id: str, timeout: int = 120) -> str:
        task_url = urljoin(self._base_url, f"/_plugins/_ml/tasks/{task_id}")
        deadline = time.time() + timeout
        model_id: Optional[str] = None
        while time.time() < deadline:
            try:
                response = requests.get(task_url, timeout=self._timeout)
                response.raise_for_status()
            except requests.RequestException as exc:
                LOGGER.debug("Waiting for ML Commons task %s failed: %s", task_id, exc)
                time.sleep(2)
                continue
            data = response.json()
            task = data.get("task") or data
            state = (task.get("state") or task.get("status") or "").lower()
            model_id = task.get("model_id") or model_id
            if state in {"completed", "success", "finished"}:
                break
            if state in {"failed", "error"}:
                raise MLCommonsError(f"ML Commons task {task_id} failed: {data}")
            time.sleep(2)
        if not model_id:
            raise MLCommonsError(f"Timed out waiting for ML Commons task {task_id}")
        return model_id

    @staticmethod
    def _extract_vector(payload: Dict[str, Any]) -> List[float]:
        if isinstance(payload.get("output"), list):
            return RemoteModelManager._normalise_vector(payload["output"])
        if isinstance(payload.get("response"), list):
            return RemoteModelManager._normalise_vector(payload["response"])
        if isinstance(payload.get("embedding"), list):
            return RemoteModelManager._normalise_vector(payload["embedding"])
        return []

    @staticmethod
    def _normalise_vector(values: Any) -> List[float]:
        if isinstance(values, list):
            return [float(item) for item in values]
        return []
