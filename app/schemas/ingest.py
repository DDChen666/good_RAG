"""Pydantic models for ingestion requests."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CrawlOptions(BaseModel):
    max_depth: Optional[int] = Field(default=None, ge=0)
    max_pages: Optional[int] = Field(default=None, ge=1)
    same_domain_only: Optional[bool] = None
    allow_subdomains: Optional[bool] = None
    include_paths: Optional[List[str]] = None
    exclude_paths: Optional[List[str]] = None
    rate_limit_per_sec: Optional[float] = Field(default=None, ge=0.1)


class IngestRequest(BaseModel):
    pdf_paths: Optional[List[str]] = None
    md_paths: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    crawl: Optional[CrawlOptions] = None


class IngestJobResponse(BaseModel):
    job_id: str
