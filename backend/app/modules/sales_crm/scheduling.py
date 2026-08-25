from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.project_team.service import eligible_sales_assignments, select_next_sales_user
from app.modules.users.models import User

from .models import (
    CalendarConnection, FunnelStage, Lead, Meeting, MeetingStatus,
    SalesAvailabilityBlock, SalesAvailabilityWindow,
)


ACTIVE_MEETING_STATUSES = {MeetingStatus.SCHEDULED, MeetingStatus.CONFIRMED}


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown timezone: {name}") from exc


def replace_availability(
    db: Session,
    *,
    user: User,
    timezone_name: str,
    windows: list[dict],
) -> list[SalesAvailabilityWindow]:
    _zone(timezone_name)
    db.query(SalesAvailabilityWindow).filter(SalesAvailabilityWindow.user_id == user.id).delete(
        synchronize_session=False,
    )
    result = []
    for value in windows:
        item = SalesAvailabilityWindow(
            user_id=user.id,
            timezone=timezone_name,
            weekday=value["weekday"],
            start_time=value["start_time"],
            end_time=value["end_time"],
            is_active=value.get("is_active", True),
        )
        db.add(item)
        result.append(item)
    db.commit()
    for item in result:
        db.refresh(item)
    return result


def availability_for_user(db: Session, user_id: str) -> list[SalesAvailabilityWindow]:
    return db.query(SalesAvailabilityWindow).filter(
        SalesAvailabilityWindow.user_id == user_id,
    ).order_by(SalesAvailabilityWindow.weekday, SalesAvailabilityWindow.start_time).all()


def _utc_naive(value: datetime, timezone_name: str) -> datetime:
    zone = _zone(timezone_name)
    localized = value.replace(tzinfo=zone) if value.tzinfo is None else value
    return localized.astimezone(timezone.utc).replace(tzinfo=None)


def create_availability_block(
    db: Session, *, user: User, starts_at: datetime, ends_at: datetime, timezone_name: str,
) -> SalesAvailabilityBlock:
    start_utc = _utc_naive(starts_at, timezone_name)
    end_utc = _utc_naive(ends_at, timezone_name)
    if end_utc <= start_utc:
        raise HTTPException(status_code=422, detail="End time must be after start time.")
    overlap = db.query(SalesAvailabilityBlock).filter(
        SalesAvailabilityBlock.user_id == user.id,
        SalesAvailabilityBlock.starts_at < end_utc,
        SalesAvailabilityBlock.ends_at > start_utc,
    ).first()
    if overlap:
        raise HTTPException(status_code=409, detail="This availability overlaps an existing block.")
    item = SalesAvailabilityBlock(
        user_id=user.id, starts_at=start_utc, ends_at=end_utc, timezone=timezone_name,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def availability_blocks_for_user(
    db: Session, *, user_id: str, starts_at: datetime, ends_at: datetime,
) -> list[SalesAvailabilityBlock]:
    start_utc = starts_at.astimezone(timezone.utc).replace(tzinfo=None) if starts_at.tzinfo else starts_at
    end_utc = ends_at.astimezone(timezone.utc).replace(tzinfo=None) if ends_at.tzinfo else ends_at
    return db.query(SalesAvailabilityBlock).filter(
        SalesAvailabilityBlock.user_id == user_id,
        SalesAvailabilityBlock.starts_at < end_utc,
        SalesAvailabilityBlock.ends_at > start_utc,
    ).order_by(SalesAvailabilityBlock.starts_at).all()


def delete_availability_block(db: Session, *, user_id: str, block_id: str) -> None:
    item = db.query(SalesAvailabilityBlock).filter(
        SalesAvailabilityBlock.id == block_id,
        SalesAvailabilityBlock.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Availability block not found.")
    db.delete(item); db.commit()


def update_availability_block(
    db: Session, *, user: User, block_id: str, starts_at: datetime, ends_at: datetime,
    timezone_name: str,
) -> SalesAvailabilityBlock:
    _zone(timezone_name)
    start_utc = _utc_naive(starts_at, timezone_name)
    end_utc = _utc_naive(ends_at, timezone_name)
    if end_utc <= start_utc:
        raise HTTPException(status_code=422, detail="End time must be after start time.")
    item = db.query(SalesAvailabilityBlock).filter(
        SalesAvailabilityBlock.id == block_id, SalesAvailabilityBlock.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Availability block not found.")
    overlap = db.query(SalesAvailabilityBlock).filter(
        SalesAvailabilityBlock.user_id == user.id,
        SalesAvailabilityBlock.id != item.id,
        SalesAvailabilityBlock.starts_at < end_utc,
        SalesAvailabilityBlock.ends_at > start_utc,
    ).first()
    if overlap:
        raise HTTPException(status_code=409, detail="This availability overlaps an existing block.")
    item.starts_at = start_utc
    item.ends_at = end_utc
    item.timezone = timezone_name
    db.add(item); db.commit(); db.refresh(item)
    return item


def upsert_calendar_connection(
    db: Session,
    *,
    user_id: str,
    provider: str,
    calendar_id: str,
) -> CalendarConnection:
    item = db.query(CalendarConnection).filter(
        CalendarConnection.user_id == user_id,
        CalendarConnection.provider == provider,
    ).first()
    if not item:
        item = CalendarConnection(
            user_id=user_id,
            provider=provider,
            access_token_ciphertext="",
        )
    item.calendar_id = calendar_id
    # OAuth transport is deliberately not faked.  This status tells the UI that
    # the simulation contract is configured but no external event was written.
    item.status = "simulation_ready"
    item.last_error = None
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def calendar_connections_for_user(db: Session, user_id: str) -> list[CalendarConnection]:
    return db.query(CalendarConnection).filter(CalendarConnection.user_id == user_id).all()


def _is_free(
    db: Session,
    *,
    user_id: str,
    starts_at: datetime,
    ends_at: datetime,
) -> bool:
    meetings = db.query(Meeting).filter(
        Meeting.assigned_sales_user_id == user_id,
        Meeting.status.in_(ACTIVE_MEETING_STATUSES),
        Meeting.meeting_time < ends_at,
    ).all()
    return not any(
        meeting.meeting_time + timedelta(minutes=meeting.duration_minutes) > starts_at
        for meeting in meetings
    )


def eligible_users_for_slot(
    db: Session,
    *,
    project_id: str,
    starts_at: datetime,
    duration_minutes: int,
) -> list[str]:
    starts_at = starts_at.replace(tzinfo=None) if starts_at.tzinfo else starts_at
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    eligible = []
    for assignment in eligible_sales_assignments(db, project_id):
        date_blocks = availability_blocks_for_user(
            db, user_id=assignment.user_id, starts_at=starts_at, ends_at=ends_at,
        )
        if any(block.starts_at <= starts_at and block.ends_at >= ends_at for block in date_blocks):
            if _is_free(db, user_id=assignment.user_id, starts_at=starts_at, ends_at=ends_at):
                eligible.append(assignment.user_id)
            continue
        windows = availability_for_user(db, assignment.user_id)
        for window in windows:
            zone = _zone(window.timezone)
            local_start = starts_at.replace(tzinfo=timezone.utc).astimezone(zone)
            local_end = ends_at.replace(tzinfo=timezone.utc).astimezone(zone)
            if local_start.weekday() != window.weekday or local_end.date() != local_start.date():
                continue
            window_start = time.fromisoformat(window.start_time)
            window_end = time.fromisoformat(window.end_time)
            if window.is_active and local_start.time() >= window_start and local_end.time() <= window_end:
                if _is_free(db, user_id=assignment.user_id, starts_at=starts_at, ends_at=ends_at):
                    eligible.append(assignment.user_id)
                break
    return eligible


def available_slots(
    db: Session,
    *,
    project_id: str,
    after: datetime,
    duration_minutes: int = 45,
    days: int = 14,
    limit: int = 12,
) -> list[dict]:
    after = after.replace(tzinfo=None) if after.tzinfo else after
    minute = 0 if after.minute < 30 else 30
    cursor = after.replace(minute=minute, second=0, microsecond=0)
    if cursor <= after:
        cursor += timedelta(minutes=30)
    end = after + timedelta(days=days)
    result = []
    while cursor < end and len(result) < limit:
        user_ids = eligible_users_for_slot(
            db,
            project_id=project_id,
            starts_at=cursor,
            duration_minutes=duration_minutes,
        )
        if user_ids:
            result.append({
                "start_at": cursor,
                "end_at": cursor + timedelta(minutes=duration_minutes),
                "eligible_sales_users": len(user_ids),
            })
        cursor += timedelta(minutes=30)
    return result


def create_agent_appointment(
    db: Session,
    *,
    lead: Lead,
    starts_at: datetime,
    duration_minutes: int,
    modality: str,
) -> tuple[Meeting, User]:
    starts_at = starts_at.replace(tzinfo=None) if starts_at.tzinfo else starts_at
    eligible_user_ids = eligible_users_for_slot(
        db,
        project_id=lead.project_id,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
    )
    if not eligible_user_ids:
        raise HTTPException(status_code=409, detail="That appointment time is no longer available.")
    assigned_user_id = select_next_sales_user(
        db,
        lead.project_id,
        eligible_user_ids=set(eligible_user_ids),
    )
    if not assigned_user_id:
        raise HTTPException(status_code=409, detail="No eligible Sales user is available for this time.")
    user = db.query(User).filter(User.id == assigned_user_id, User.company_id == lead.company_id).one()
    connections = calendar_connections_for_user(db, user.id)
    meeting = Meeting(
        project_id=lead.project_id,
        lead_id=lead.id,
        broker_id=None,
        assigned_sales_user_id=user.id,
        meeting_time=starts_at,
        duration_minutes=duration_minutes,
        modality=modality,
        confirmation_status="confirmed",
        calendar_sync_status="simulation_ready" if connections else "not_connected",
        status=MeetingStatus.CONFIRMED,
        is_demo=True,
        source="agent_simulation",
        notes="Appointment confirmed in the AI Sales Agent simulation.",
    )
    lead.assigned_sales_user_id = user.id
    lead.funnel_stage = FunnelStage.APPOINTMENT_SET
    lead.stage_changed_at = datetime.utcnow()
    db.add_all([meeting, lead])
    db.flush()
    return meeting, user
