"""Small database-backed worker for production SMS follow-up jobs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging

from sqlalchemy import and_, or_

from app.db.postgres import SessionLocal
from app.modules.governance.services import process_notification_outbox

from .live_service import process_live_followup_job, process_live_inbound_job
from .models import SalesConversation, SalesFollowUpJob, SalesInboundJob

logger = logging.getLogger(__name__)


def _process_operational_outboxes() -> None:
    db = SessionLocal()
    try:
        process_notification_outbox(db)
    finally:
        db.close()


def _claim_due_jobs(limit: int = 10) -> list[str]:
    db = SessionLocal()
    try:
        jobs = (
            db.query(SalesFollowUpJob)
            .join(SalesConversation, SalesConversation.id == SalesFollowUpJob.conversation_id)
            .filter(
                SalesFollowUpJob.status == "pending",
                SalesFollowUpJob.scheduled_at <= datetime.utcnow(),
                SalesConversation.channel.in_(("sms", "whatsapp")),
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


def _recover_stale_inbound_jobs() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        db.query(SalesInboundJob).filter(
            SalesInboundJob.status == "processing",
            SalesInboundJob.claimed_at < cutoff,
        ).update({
            SalesInboundJob.status: "retry",
            SalesInboundJob.scheduled_at: datetime.utcnow(),
            SalesInboundJob.claimed_at: None,
            SalesInboundJob.error_code: "STALE_CLAIM",
            SalesInboundJob.error_message: "Recovered an interrupted agent turn.",
        }, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _claim_inbound_jobs(limit: int = 10) -> list[str]:
    """Claim FIFO work while never claiming two turns from the same conversation."""
    db = SessionLocal()
    try:
        candidates = (
            db.query(SalesInboundJob)
            .filter(
                SalesInboundJob.status.in_(("pending", "retry")),
                SalesInboundJob.scheduled_at <= datetime.utcnow(),
            )
            .order_by(SalesInboundJob.created_at, SalesInboundJob.id)
            .with_for_update(skip_locked=True)
            .limit(max(limit * 5, 25))
            .all()
        )
        claimed: list[SalesInboundJob] = []
        conversations: set[str] = set()
        for job in candidates:
            if len(claimed) >= limit or job.conversation_id in conversations:
                continue
            older_exists = db.query(SalesInboundJob.id).filter(
                SalesInboundJob.conversation_id == job.conversation_id,
                SalesInboundJob.status.in_(("pending", "retry", "processing")),
                or_(
                    SalesInboundJob.created_at < job.created_at,
                    and_(SalesInboundJob.created_at == job.created_at, SalesInboundJob.id < job.id),
                ),
            ).first()
            if older_exists:
                continue
            job.status = "processing"
            job.claimed_at = datetime.utcnow()
            job.attempt_number = (job.attempt_number or 0) + 1
            claimed.append(job)
            conversations.add(job.conversation_id)
        db.commit()
        return [job.id for job in claimed]
    finally:
        db.close()


async def run_live_followup_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(_process_operational_outboxes)
        except Exception:
            logger.exception("Operational notification outbox processing failed")
        try:
            await asyncio.to_thread(_recover_stale_inbound_jobs)
            inbound_ids = await asyncio.to_thread(_claim_inbound_jobs)
        except Exception:
            logger.exception("Inbound agent queue claim failed")
            inbound_ids = []
        for job_id in inbound_ids:
            try:
                await process_live_inbound_job(job_id)
            except Exception:
                logger.exception("Live inbound agent turn failed", extra={"job_id": job_id})
        for job_id in await asyncio.to_thread(_claim_due_jobs):
            try:
                await process_live_followup_job(job_id)
            except Exception:
                logger.exception("Live SMS follow-up failed", extra={"job_id": job_id})
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
