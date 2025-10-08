"""Celery application definition."""

from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "good_rag_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.task_track_started = True
celery_app.conf.result_expires = 3600
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.autodiscover_tasks(packages=["app.worker"])


@celery_app.task(name="worker.healthcheck")
def healthcheck() -> str:
    """Simple Celery task used by the API to verify connectivity."""

    return "ok"
