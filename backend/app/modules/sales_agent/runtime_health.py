"""Read-only health projects actual scans, not a timer or onboarding heartbeat."""
from datetime import datetime,timedelta
import uuid
from app.core.config import settings
from app.db.postgres import SessionLocal
from .models import SalesWorkerProgress,SalesInboundJob,SalesFollowUpJob

INSTANCE_ID=str(uuid.uuid4())
PHASES=('inbound','followup','calendar','waits','outbox')


def record(phase,*,error=None,completed=False,stop=False):
    db=SessionLocal()
    try:
        now=datetime.utcnow()
        row=db.query(SalesWorkerProgress).filter_by(id=INSTANCE_ID).with_for_update().first()
        if not row:
            row=SalesWorkerProgress(id=INSTANCE_ID,commit_sha=settings.APP_COMMIT_SHA,progress_json={},last_progress_at=now)
            db.add(row)
        progress=dict(row.progress_json or {});entry=dict(progress.get(phase) or {})
        entry['status']='error' if error else 'ok'
        entry['error_type']=type(error).__name__ if error else None
        if completed:
            entry['completed_at']=now.isoformat();entry['completed_jobs']=entry.get('completed_jobs',0)+1
        else:entry['scan_at']=now.isoformat()
        progress[phase]=entry;row.progress_json=progress;row.last_progress_at=now
        if stop:row.stopped_at=now
        db.commit()
    finally:db.close()


def snapshot(db,*,now=None,instance_id=None):
    now=now or datetime.utcnow();row=db.get(SalesWorkerProgress,instance_id or INSTANCE_ID)
    result={'workflow_version':'sales-current/1.0','commit':settings.APP_COMMIT_SHA,'worker_status':'not_started','attention_required':False}
    if not row:return {**result,'status':'not_ready'}
    age=(now-row.last_progress_at).total_seconds();phases=row.progress_json or {}
    healthy=row.commit_sha==settings.APP_COMMIT_SHA and row.stopped_at is None and 0<=age<=180
    scans={}
    for name in PHASES:
        phase=phases.get(name) or {}
        try:scan_age=(now-datetime.fromisoformat(phase['scan_at'])).total_seconds()
        except (KeyError,ValueError,TypeError):scan_age=None
        ok=phase.get('status')=='ok' and scan_age is not None and 0<=scan_age<=600
        healthy=healthy and ok
        scans[name]={'status':'ok' if ok else 'not_ready','scan_age_seconds':round(scan_age,1) if scan_age is not None else None,
            'completed_jobs':phase.get('completed_jobs',0)}
    attention=bool(db.query(SalesInboundJob.id).filter(SalesInboundJob.status.in_(['failed','review'])).first() or
        db.query(SalesFollowUpJob.id).filter(SalesFollowUpJob.status.in_(['failed','review'])).first())
    overdue=bool(db.query(SalesInboundJob.id).filter(SalesInboundJob.status.in_(['pending','retry']),SalesInboundJob.scheduled_at<now-timedelta(minutes=10)).first() or
        db.query(SalesFollowUpJob.id).filter(SalesFollowUpJob.status=='pending',SalesFollowUpJob.scheduled_at<now-timedelta(minutes=10)).first())
    return {**result,'status':'ready' if healthy else 'not_ready','worker_status':'scanning' if healthy else 'stale_or_failed',
        'progress_age_seconds':round(age,1),'scans':scans,'attention_required':attention,'overdue_work':overdue,
        'receipt_semantics':'Worker scans/completions do not prove provider delivery or business acceptance.'}
