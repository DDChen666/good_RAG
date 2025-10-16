"""Celery task definitions for ingestion and indexing."""

from __future__ import annotations

import uuid
from datetime import datetime
from hashlib import sha1
from pathlib import Path
from typing import Any, Dict, List, Optional

from celery.result import AsyncResult

from app.config import settings
from app.ingestors.md import normalise_markdown
from app.ingestors.pdf import extract_text
from app.ingestors.web import CrawlConfig, fetch_pages, plan_crawl
from app.preproc.chunker import Node, chunk_nodes
from app.search.embedding import embedding_client
from app.search.opensearch_client import client as opensearch_client
from app.worker.app import celery_app


@celery_app.task(bind=True, name="worker.ingest")
def run_ingest(self, payload: Dict[str, object]) -> Dict[str, object]:
    """Ingest PDFs/Markdown/URLs, index chunks into OpenSearch, and report."""

    def _as_paths(items: Any) -> List[Path]:
        return [Path(item) for item in items or []]

    def _parse_optional_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in {"true", "1", "yes", "y"}:
                return True
            if value.lower() in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    pdf_paths = _as_paths(payload.get("pdf_paths"))
    md_paths = _as_paths(payload.get("md_paths"))
    urls: List[str] = [str(url) for url in payload.get("urls", []) or []]
    crawl_params = payload.get("crawl", {}) or {}
    crawl_config = CrawlConfig(
        max_depth=int(crawl_params.get("max_depth", settings.max_crawl_depth)),
        max_pages=int(crawl_params.get("max_pages", settings.max_crawl_pages)),
        same_domain_only=_parse_optional_bool(crawl_params.get("same_domain_only"), settings.same_domain_only),
        allow_subdomains=_parse_optional_bool(crawl_params.get("allow_subdomains"), settings.allow_subdomains),
        include_paths=crawl_params.get("include_paths"),
        exclude_paths=crawl_params.get("exclude_paths"),
        rate_limit_per_sec=float(crawl_params.get("rate_limit_per_sec", settings.rate_limit_per_sec)),
    )

    pdf_texts = extract_text(pdf_paths)
    md_texts = normalise_markdown(md_paths)
    crawl_plan = plan_crawl(urls, crawl_config)
    fetched_pages = fetch_pages(crawl_plan)

    nodes: List[Node] = []
    ingested_sources: List[Dict[str, Any]] = []

    for path, text in zip(pdf_paths, pdf_texts):
        metadata = {
            "doc_id": f"pdf::{path.resolve()}",
            "source": "pdf",
            "url": str(path.resolve()),
        }
        if text.strip():
            nodes.append(Node(content=text, metadata=metadata))
        ingested_sources.append({"type": "pdf", "path": str(path), "bytes": path.stat().st_size if path.exists() else 0})

    for path, text in zip(md_paths, md_texts):
        metadata = {
            "doc_id": f"md::{path.resolve()}",
            "source": "markdown",
            "url": str(path.resolve()),
        }
        if text.strip():
            nodes.append(Node(content=text, metadata=metadata))
        ingested_sources.append({"type": "markdown", "path": str(path)})

    for url, text in fetched_pages:
        metadata = {"doc_id": f"url::{url}", "source": "url", "url": url}
        if text.strip():
            nodes.append(Node(content=text, metadata=metadata))
        ingested_sources.append({"type": "url", "url": url, "bytes": len(text.encode("utf-8"))})

    chunks = list(
        chunk_nodes(
            nodes,
            target_size=settings.chunk_target_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
    )
    chunk_documents: List[Dict[str, Any]] = []
    skipped_chunks: List[Dict[str, Any]] = []
    now = datetime.utcnow().isoformat() + "Z"

    for chunk in chunks:
        metadata = chunk.metadata.copy()
        doc_id = metadata.get("doc_id", str(uuid.uuid4()))
        chunk_index = metadata.get("chunk_index", 0)
        doc_key = f"{doc_id}::{chunk_index}"
        document = {
            "doc_key": doc_key,
            "content": chunk.content,
            "node_type": metadata.get("node_type", "text"),
            "h_path": chunk.h_path or [],
            "source": metadata.get("source"),
            "url": metadata.get("url"),
            "version": metadata.get("version"),
            "last_seen_at": now,
            "content_hash": sha1(chunk.content.encode("utf-8")).hexdigest(),
        }
        chunk_documents.append(document)

    vectors = embedding_client.embed(doc["content"] for doc in chunk_documents)
    indexable_docs: List[Dict[str, Any]] = []
    for document, vector in zip(chunk_documents, vectors):
        if vector:
            document["content_vector"] = vector
            indexable_docs.append(document)
        else:
            document["error"] = "embedding_failed"
            skipped_chunks.append(document)

    if indexable_docs:
        opensearch_client.ensure_index()
        opensearch_client.bulk_index(indexable_docs)

    return {
        "sources": ingested_sources,
        "crawl_plan": crawl_plan,
        "fetched_pages": [url for url, _ in fetched_pages],
        "chunk_count": len(chunks),
        "indexed_chunks": len(indexable_docs),
        "skipped_chunks": [doc["doc_key"] for doc in skipped_chunks],
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
