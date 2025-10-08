"""Regex-based metadata extraction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Pattern


@dataclass
class ExtractionResult:
    matches: List[str]


class RegexExtractor:
    """Utility class for reusing compiled regular expressions."""

    def __init__(self, pattern: str) -> None:
        self.pattern: Pattern[str] = re.compile(pattern, flags=re.IGNORECASE)

    def extract(self, text: str) -> ExtractionResult:
        return ExtractionResult(matches=self.pattern.findall(text))


ENDPOINT_PATTERN = r"(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/[\w\-/{}/.]+)"
PARAM_PATTERN = r"\"([a-zA-Z0-9_]+)\"\s*:"
ERROR_PATTERN = r"\b(4\d{2}|5\d{2})\b"

endpoint_extractor = RegexExtractor(ENDPOINT_PATTERN)
param_extractor = RegexExtractor(PARAM_PATTERN)
error_extractor = RegexExtractor(ERROR_PATTERN)


def extract_all(texts: Iterable[str]) -> List[ExtractionResult]:
    """Apply all extractors to the provided texts and collate results."""

    results: List[ExtractionResult] = []
    for text in texts:
        endpoint_matches = endpoint_extractor.extract(text)
        param_matches = param_extractor.extract(text)
        error_matches = error_extractor.extract(text)
        results.extend([endpoint_matches, param_matches, error_matches])
    return results
