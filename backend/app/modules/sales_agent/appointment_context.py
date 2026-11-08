"""Scoped appointment reads and explicit booking references. No calendar writes."""
from datetime import datetime, timezone, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel,ConfigDict,Field
from app.modules.sales_crm.models import Meeting,MeetingStatus,Lead
from app.modules.projects.models import Project,ProjectPropertyType,ProjectUnit
from app.modules.users.models import User

ACTIVE={MeetingStatus.SCHEDULED,MeetingStatus.CONFIRMED,MeetingStatus.IN_PROGRESS}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def bind_visit(db,meeting,*,company_id,property_type_id=None,unit_id=None):
    """Called only with an explicit selection at booking, never historical backfill."""
    project=db.query(Project).filter_by(id=meeting.project_id,company_id=company_id).one_or_none()
    lead=db.query(Lead).filter_by(id=meeting.lead_id,company_id=company_id,deleted_at=None).one_or_none()
    if not project or not lead:raise PermissionError('Booking references are outside this Company/lead.')
    product=db.query(ProjectPropertyType).filter_by(id=property_type_id,project_id=project.id,review_status='confirmed').one_or_none() if property_type_id else None
    unit=db.query(ProjectUnit).filter_by(id=unit_id,project_id=project.id).one_or_none() if unit_id else None
    if property_type_id and not product or unit_id and not unit:raise PermissionError('Booking property references are not approved in this Project.')
    # Units currently store a text typology, not a relational type ID. Do not
    # infer their association by a similar label. The approved catalog must agree.
    product_data=unit_data=None
    if product or unit:
        from .commercial_context import build_commercial_context
        context=build_commercial_context(db,project=project,company_id=company_id,lead_id=lead.id)
        product_data=next((r for r in context['property_types'] if product and r['id']==product.id),None)
        unit_data=next((r for r in context['inventory'] if unit and r['id']==unit.id),None)
        if product and not product_data:raise PermissionError('Type is not in the approved catalog.')
        if unit and not unit_data:raise PermissionError('Unit is not in the approved inventory.')
        if product and unit and unit_data.get('property_type')!=product_data['property_type']:raise PermissionError('Unit/type relationship is not explicit in approved data.')
    meeting.visit_property_type_id=property_type_id
    meeting.visit_unit_id=unit_id
    meeting.visit_context={'version':'sales-visit-context/1.0','source':'explicit_booking_selection',
        'project_id':project.id,'project_name':project.name,'property_type_id':property_type_id,
        'property_type_name':product_data['property_type'] if product_data else None,'unit_id':unit_id,'unit_code':unit_data['unit_code'] if unit_data else None,
        'timezone':project.timezone or 'UTC','property_association':'explicit' if product or unit else 'unknown'}
    return meeting.visit_context


class AppointmentQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    category:Literal['active','past','cancelled','all']='active'
    meeting_id:str|None=Field(default=None,max_length=36)
    limit:int=Field(default=10,ge=1,le=30,strict=True)


class AppointmentReadTool:
    def __init__(self,db,scope):self.db,self.scope=db,scope

    def execute(self,query=None,*,now=None):
        from .dialogue_store import check_scope
        check_scope(self.db,self.scope)
        query=AppointmentQuery.model_validate(query or {})
        now=utc(now or datetime.now(timezone.utc))
        rows=self.db.query(Meeting,Project).join(Project,Project.id==Meeting.project_id).filter(
            Meeting.lead_id==self.scope.lead_id,Project.company_id==self.scope.company_id)
        if query.meeting_id:rows=rows.filter(Meeting.id==query.meeting_id)
        # Filter in SQL before limiting, including a visit currently in progress.
        if query.category=='cancelled':rows=rows.filter(Meeting.status==MeetingStatus.CANCELLED)
        elif query.category=='active':rows=rows.filter(Meeting.status.in_(list(ACTIVE)),Meeting.meeting_time>=now.replace(tzinfo=None)-timedelta(hours=8))
        elif query.category=='past':
            from sqlalchemy import or_
            rows=rows.filter(Meeting.status!=MeetingStatus.CANCELLED,or_(~Meeting.status.in_(list(ACTIVE)),Meeting.meeting_time<=now.replace(tzinfo=None)))
        rows=rows.order_by(Meeting.meeting_time.desc() if query.category in {'past','cancelled','all'} else Meeting.meeting_time).limit(201).all()
        scan_truncated=len(rows)>200
        output=[]
        for meeting,project in rows[:200]:
            active=meeting.status in ACTIVE and utc(meeting.meeting_time)+timedelta(minutes=meeting.duration_minutes)>now
            if query.category=='active' and not active or query.category=='past' and active:continue
            snapshot=meeting.visit_context or {}
            zone_name=snapshot.get('timezone') or project.timezone or 'UTC'
            try:zone=ZoneInfo(zone_name);zone_issue=None
            except (ZoneInfoNotFoundError,ValueError):zone=timezone.utc;zone_issue='invalid_project_timezone_using_utc'
            user=self.db.query(User).filter_by(id=meeting.assigned_sales_user_id,company_id=self.scope.company_id,deleted_at=None).one_or_none() if meeting.assigned_sales_user_id else None
            output.append({'id':meeting.id,'project_id':meeting.project_id,'project_name':snapshot.get('project_name') or project.name,
                'property_type_id':meeting.visit_property_type_id,'unit_id':meeting.visit_unit_id,
                'property_type_name':snapshot.get('property_type_name'),'unit_code':snapshot.get('unit_code'),
                'property_association':snapshot.get('property_association') or 'unknown_legacy',
                'status':meeting.status.value,'category':'cancelled' if meeting.status==MeetingStatus.CANCELLED else 'active' if active else 'past',
                'starts_at_utc':utc(meeting.meeting_time).isoformat(),'starts_at_local':utc(meeting.meeting_time).astimezone(zone).isoformat(),
                'timezone':str(zone),'timezone_source':'booking_snapshot' if snapshot.get('timezone') else 'current_project_legacy_fallback',
                'timezone_issue':zone_issue,'duration_minutes':meeting.duration_minutes,
                'address':meeting.visit_address,'location_label':meeting.visit_location_label,
                'location_status':meeting.location_confirmation_status,
                'specialist_name':' '.join(v for v in (user.first_name,user.last_name) if v).strip() if user else None,
                'confirmation_status':meeting.confirmation_status})
        return {'version':'sales-appointment-read/1.0','category':query.category,'appointments':output[:query.limit],
                'count':len(output),'count_is_lower_bound':scan_truncated,'truncated':scan_truncated or len(output)>query.limit,'external_actions':0,
                'scope':{'company_id':self.scope.company_id,'lead_id':self.scope.lead_id}}


def render(result):
    rows=result['appointments']
    if not rows:
        if result['truncated']:return 'I could not fully inspect your appointment history. Please specify which date you want to review.'
        return 'You have no '+({'active':'active','past':'past','cancelled':'cancelled'}.get(result['category'],'recorded'))+' appointments.'
    blocks=[]
    for row in rows:
        when=datetime.fromisoformat(row['starts_at_local']).strftime('%Y-%m-%d at %H:%M')
        parts=[f"{row['project_name']}: {when} ({row['timezone']}); status: {row['status']}."]
        if row['property_type_name']:parts.append('Property: '+row['property_type_name']+'.')
        if row['unit_code']:parts.append('Unit: '+row['unit_code']+'.')
        if row['address']:parts.append('Visit address: '+row['address']+'.')
        else:parts.append('The visit address has not been recorded.')
        if row['specialist_name']:parts.append('Your specialist: '+row['specialist_name']+'.')
        else:parts.append('The specialist details are not available.')
        if row['property_association'].startswith('unknown'):parts.append('The specific property type or unit was not recorded for this appointment.')
        blocks.append(' '.join(parts))
    if result['truncated']:blocks.append('There are more recorded appointments; please specify which date you want to review.')
    return '\n\n'.join(blocks)
