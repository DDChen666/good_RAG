"""Status and source response models."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    worker: str
    opensearch: str
    ollama: str


class Source(BaseModel):
    id: str
    name: str
    document_count: int


class SourceListResponse(BaseModel):
    sources: List[Source]

    class Config:
        json_schema_extra = {
            "example": {
                "sources": [
                    {"id": "openai", "name": "OpenAI Docs", "document_count": 42}
                ]
            }
        }
