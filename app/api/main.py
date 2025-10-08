"""FastAPI application exposing ingestion and query endpoints."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas.ingest import IngestJobResponse, IngestRequest
from app.schemas.query import QueryRequest, QueryResponse
from app.schemas.status import HealthStatus, SourceListResponse
from app.search.service import search_service
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
    return SourceListResponse(sources=[])


@app.get("/status/health", response_model=HealthStatus, dependencies=[Depends(verify_api_key)])
def health() -> HealthStatus:
    worker_status = "unknown"
    try:
        celery_state = healthcheck.delay()
        worker_status = celery_state.get(timeout=10)
    except Exception:  # pragma: no cover - connection failures surface as warnings
        worker_status = "unavailable"
    return HealthStatus(status="ok", worker=worker_status, opensearch="unknown", ollama="unknown")


@app.get("/status/uuid")
def random_uuid() -> dict:
    return {"uuid": str(uuid.uuid4())}
