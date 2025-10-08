"""Celery task definitions for ingestion and indexing."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, Optional

from celery.result import AsyncResult

from app.config import settings
from app.ingestors.md import normalise_markdown
from app.ingestors.pdf import extract_text
from app.ingestors.web import CrawlConfig, plan_crawl
from app.preproc.chunker import Node, chunk_nodes
from app.worker.app import celery_app


@celery_app.task(bind=True, name="worker.ingest")
def run_ingest(self, payload: Dict[str, object]) -> Dict[str, object]:
    """Coarse ingestion pipeline that records the planned operations."""

    pdf_docs = extract_text(Path(path) for path in payload.get("pdf_paths", []))
    md_docs = normalise_markdown(Path(path) for path in payload.get("md_paths", []))
    urls = payload.get("urls", []) or []
    crawl_params = payload.get("crawl", {}) or {}
    crawl_config = CrawlConfig(
        max_depth=int(crawl_params.get("max_depth", settings.max_crawl_depth)),
        max_pages=int(crawl_params.get("max_pages", settings.max_crawl_pages)),
        same_domain_only=bool(crawl_params.get("same_domain_only", settings.same_domain_only)),
        allow_subdomains=bool(crawl_params.get("allow_subdomains", settings.allow_subdomains)),
        include_paths=crawl_params.get("include_paths"),
        exclude_paths=crawl_params.get("exclude_paths"),
        rate_limit_per_sec=float(crawl_params.get("rate_limit_per_sec", settings.rate_limit_per_sec)),
    )
    crawl_plan = plan_crawl(urls, crawl_config)

    nodes = [Node(content=doc) for doc in [*pdf_docs, *md_docs]]
    chunks = list(chunk_nodes(nodes))

    return {
        "pdf_docs": pdf_docs,
        "md_docs": md_docs,
        "crawl_plan": crawl_plan,
        "chunk_count": len(chunks),
    }


def enqueue_ingest_job(payload: Dict[str, object]) -> str:
    job_id = f"ingest-{uuid.uuid4()}"
    run_ingest.apply_async(args=(payload,), task_id=job_id)
    return job_id


def get_job_status(job_id: str) -> Dict[str, object]:
    result = AsyncResult(job_id, app=celery_app)
    info: Optional[Dict[str, object]]
    if result.successful():
        info = result.result  # type: ignore[assignment]
    else:
        info = None
    return {
        "job_id": job_id,
        "state": result.state,
        "result": info,
    }
