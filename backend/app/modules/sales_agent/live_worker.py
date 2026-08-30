"""Small database-backed worker for production SMS follow-up jobs."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging

from app.db.postgres import SessionLocal

from .live_service import process_live_followup_job
from .models import SalesConversation, SalesFollowUpJob

logger = logging.getLogger(__name__)


def _claim_due_jobs(limit: int = 10) -> list[str]:
    db = SessionLocal()
    try:
        jobs = (
            db.query(SalesFollowUpJob)
            .join(SalesConversation, SalesConversation.id == SalesFollowUpJob.conversation_id)
            .filter(
                SalesFollowUpJob.status == "pending",
                SalesFollowUpJob.scheduled_at <= datetime.utcnow(),
                SalesConversation.channel == "sms",
            )
            .order_by(SalesFollowUpJob.scheduled_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        ids = [job.id for job in jobs]
        for job in jobs:
            job.status = "processing"
        db.commit()
        return ids
    finally:
        db.close()


async def run_live_followup_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        for job_id in await asyncio.to_thread(_claim_due_jobs):
            try:
                await process_live_followup_job(job_id)
            except Exception:
                logger.exception("Live SMS follow-up failed", extra={"job_id": job_id})
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass
