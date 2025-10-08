# good_RAG

A reference implementation of the API document-centric RAG system described
in the accompanying product requirements document.  The repository provides
an end-to-end skeleton that can ingest PDFs, Markdown, and static websites,
produce hybrid BM25 + dense retrieval queries, and expose the workflow via a
FastAPI application with Celery-powered background tasks.

## Features

- **Docker Compose** bundle for OpenSearch, Redis, Ollama, FastAPI, and Celery.
- **Configurable ingestion** request model covering file paths and crawl
  options.
- **Placeholder pipelines** for PDF/Markdown/Web processing with clear
  extension points.
- **Hybrid retrieval scaffolding** including Reciprocal Rank Fusion helpers
  and OpenSearch index bootstrap that automatically detects embedding
  dimensionality from Ollama.
- **Offline evaluation skeleton** for Recall/MRR/nDCG style metrics.

## Getting Started

1. Copy `.env.example` to `.env` and adjust values as needed.
2. Ensure Docker Desktop is running, then start the stack:
   ```bash
   docker compose up --build
   ```
3. Interact with the API at `http://localhost:8000/docs`.

## Project Layout

```
app/
  api/          # FastAPI routes and application wiring
  configs/      # Synonyms and crawler configuration templates
  eval/         # Offline evaluation placeholder
  ingestors/    # PDF/Markdown/Web loaders
  preproc/      # Chunking and metadata extraction utilities
  search/       # OpenSearch client and hybrid retrieval helpers
  worker/       # Celery application and tasks
  ui/           # Front-end placeholder
```

## Development Notes

- The ingestion and retrieval components currently return mock data so the
  API can be exercised before the full pipeline is implemented.
- The OpenSearch client uses the REST API via `requests` and creates indexes
  on demand using the embedding dimensionality reported by Ollama.
- Extend `app/worker/tasks.py` to connect chunk outputs with `OpenSearchClient`
  and the embedding service to complete the indexing pipeline.
