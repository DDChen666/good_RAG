"""Static website synchronisation stubs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urlparse


def normalise_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


@dataclass
class CrawlConfig:
    max_depth: int
    max_pages: int
    same_domain_only: bool
    allow_subdomains: bool
    include_paths: Optional[List[str]] = None
    exclude_paths: Optional[List[str]] = None
    rate_limit_per_sec: float = 1.0


def plan_crawl(start_urls: Iterable[str], config: CrawlConfig) -> List[str]:
    """Return a deterministic crawl frontier for unit tests.

    Instead of performing live HTTP requests, the function normalises the
    provided URLs and truncates the list according to ``config.max_pages``.
    Real crawling can be implemented by replacing this function with a BFS
    crawler that respects robots.txt.
    """

    frontier = [normalise_url(url) for url in start_urls]
    return frontier[: config.max_pages]
