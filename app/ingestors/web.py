"""Static website synchronisation stubs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.config import settings

LOGGER = logging.getLogger(__name__)


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


def fetch_pages(urls: Iterable[str], timeout: float = settings.http_timeout) -> List[Tuple[str, str]]:
    """Download and extract readable text from the provided URLs.

    Each tuple in the returned list contains the normalised URL and the
    extracted text body.  Errors are logged and skipped so the caller can
    continue ingesting other sources.
    """

    pages: List[Tuple[str, str]] = []
    session = requests.Session()
    headers = {
        "User-Agent": "good-rag-ingest/0.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for url in urls:
        normalised = normalise_url(url)
        try:
            response = session.get(normalised, headers=headers, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup(["script", "style", "noscript"]):
                script.extract()
            text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
            if text:
                pages.append((normalised, text))
            else:
                LOGGER.warning("Fetched URL %s but extracted empty body", normalised)
        except requests.RequestException as exc:
            LOGGER.warning("Failed to fetch %s: %s", normalised, exc)
    return pages
