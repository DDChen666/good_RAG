"""Offline evaluation entry point placeholder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass
class QueryExample:
    question: str
    expected_doc_keys: List[str]


@dataclass
class EvaluationResult:
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float


def load_examples(path: Path) -> List[QueryExample]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [QueryExample(**item) for item in data]


def evaluate(retrieved: Iterable[List[str]], expected: Iterable[List[str]]) -> EvaluationResult:
    """Compute naive metrics for demonstration purposes."""

    recall = 0.0
    mrr = 0.0
    ndcg = 0.0
    count = 0
    for retrieved_docs, expected_docs in zip(retrieved, expected):
        count += 1
        hits = [doc for doc in retrieved_docs[:10] if doc in expected_docs]
        if expected_docs:
            recall += len(hits) / len(expected_docs)
        for rank, doc in enumerate(retrieved_docs[:10], start=1):
            if doc in expected_docs and mrr == 0.0:
                mrr = 1.0 / rank
                break
        if hits:
            ndcg += 1.0
    if count == 0:
        return EvaluationResult(0.0, 0.0, 0.0)
    return EvaluationResult(recall / count, mrr, ndcg / count)
