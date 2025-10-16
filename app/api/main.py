"""FastAPI application exposing ingestion and query endpoints."""

from __future__ import annotations

import uuid
from pathlib import Path as FilePath
from typing import Optional
from urllib.parse import urljoin

from fastapi import Depends, FastAPI, File, Header, HTTPException, Path, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import requests
from uuid import uuid4

from app.config import settings
from app.schemas.ingest import IngestJobResponse, IngestRequest
from app.schemas.query import QueryRequest, QueryResponse
from app.schemas.status import HealthStatus, SourceListResponse
from app.search.service import search_service
from app.search.opensearch_client import client as opensearch_client
from app.worker.app import healthcheck
from app.worker.tasks import enqueue_ingest_job, get_job_status

app = FastAPI(title="good_RAG API", version="0.1.0")

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@app.post("/ingest", response_model=IngestJobResponse, dependencies=[Depends(verify_api_key)])
def ingest(request: IngestRequest) -> IngestJobResponse:
    payload = request.dict(exclude_none=True)
    job_id = enqueue_ingest_job(payload)
    return IngestJobResponse(job_id=job_id)


@app.get("/ingest/{job_id}", dependencies=[Depends(verify_api_key)])
def ingest_status(job_id: str) -> dict:
    return get_job_status(job_id)


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(verify_api_key)])
def query(request: QueryRequest) -> QueryResponse:
    result = search_service.query(
        query=request.q,
        domain_filter=request.domain_filter,
        version=request.version,
    )
    return QueryResponse(**result)


@app.post("/sync", response_model=IngestJobResponse, dependencies=[Depends(verify_api_key)])
def sync(request: IngestRequest) -> IngestJobResponse:
    payload = request.dict(exclude_none=True)
    payload.setdefault("sync", True)
    job_id = enqueue_ingest_job(payload)
    return IngestJobResponse(job_id=job_id)


@app.get("/sources", response_model=SourceListResponse, dependencies=[Depends(verify_api_key)])
def list_sources() -> SourceListResponse:
    sources = opensearch_client.list_sources()
    return SourceListResponse(sources=sources)


@app.delete(
    "/sources/{source_id}",
    dependencies=[Depends(verify_api_key)],
)
def delete_source(
    source_id: str = Path(..., description="Base64 URL 安全編碼的資料來源 ID。"),
) -> dict:
    try:
        source_name = opensearch_client.decode_source_id(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        deleted = opensearch_client.delete_source(source_name)
    except requests.RequestException as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return {"status": "deleted", "source_id": source_id, "source": source_name, "deleted_documents": deleted}


@app.get("/status/health", response_model=HealthStatus, dependencies=[Depends(verify_api_key)])
def health() -> HealthStatus:
    worker_status = "unknown"
    try:
        celery_state = healthcheck.delay()
        worker_status = celery_state.get(timeout=10)
    except Exception:  # pragma: no cover - connection failures surface as warnings
        worker_status = "unavailable"

    def _check_opensearch() -> str:
        try:
            url = urljoin(str(settings.os_url), "/_cluster/health")
            response = requests.get(url, timeout=settings.http_timeout)
            response.raise_for_status()
            data = response.json()
            return data.get("status", "ok")
        except requests.RequestException:
            return "unavailable"

    def _check_ollama() -> str:
        try:
            url = urljoin(str(settings.ollama_url), "/api/tags")
            response = requests.get(url, timeout=settings.http_timeout)
            response.raise_for_status()
            tags = response.json().get("models", [])
            return "ok" if tags is not None else "unknown"
        except requests.RequestException:
            return "unavailable"

    return HealthStatus(status="ok", worker=worker_status, opensearch=_check_opensearch(), ollama=_check_ollama())


@app.get("/status/uuid")
def random_uuid() -> dict:
    return {"uuid": str(uuid.uuid4())}


ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".md", ".markdown", ".mdown", ".txt"}


@app.post("/upload", dependencies=[Depends(verify_api_key)])
async def upload_file(file: UploadFile = File(...)) -> dict:
    extension = FilePath(file.filename).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_id = f"{uuid4().hex}{extension}"
    destination = upload_dir / upload_id
    contents = await file.read()
    destination.write_bytes(contents)
    return {
        "upload_id": upload_id,
        "path": str(destination),
        "original_name": file.filename,
        "extension": extension,
    }


@app.delete("/upload/{upload_id}", dependencies=[Depends(verify_api_key)])
def delete_uploaded_file(upload_id: str) -> dict:
    upload_dir = settings.upload_dir
    target = upload_dir / upload_id
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    try:
        target.unlink()
    except OSError as exc:  # pragma: no cover - filesystem specific
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"status": "deleted", "upload_id": upload_id}


frontend_dir = FilePath(__file__).resolve().parents[1] / "ui" / "static"
if frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(frontend_dir), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/")
