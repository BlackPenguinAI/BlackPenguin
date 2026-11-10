"""Atomic UI-only editor transitions. Drafts never become commercial facts."""
from copy import deepcopy
from datetime import datetime
import json
import re
from fastapi import HTTPException
from sqlalchemy.orm.attributes import flag_modified
from app.modules.project_team.models import ProjectUserAssignment
from .models import ProjectPropertyType, ProjectOnboardingSource, ProjectCampaign

FOCUS = '__editor_focus__'
CARDS = {'catalog':'field:property_type_catalog','meta_account':'field:meta_connection_verified',
    'meta_assets':'field:campaigns_defined','team':'field:sales_contacts','delivery':'field:delivery_dates',
    'parking':'field:parking_and_storage','documents':'documents','location':'field:country'}


def _credentials(value):
    if isinstance(value, dict):
        return any(re.search(r'password|secret|access_token|refresh_token|api_key|authorization_header', str(k), re.I)
            or _credentials(v) for k,v in value.items())
    return isinstance(value,list) and any(_credentials(v) for v in value)


def has_saved(db, project, task):
    data=project.profile.profile_data or {}
    if task=='catalog':return db.query(ProjectPropertyType.id).filter_by(project_id=project.id).first() is not None
    if task=='documents':return db.query(ProjectOnboardingSource.id).filter_by(project_id=project.id).first() is not None
    if task=='meta_account':
        from .meta_setup_state import setup_state
        return setup_state(db,project)['account_status']!='not_connected'
    if task=='meta_assets':return db.query(ProjectCampaign.id).filter_by(project_id=project.id).first() is not None
    if task=='team':return db.query(ProjectUserAssignment.id).filter_by(project_id=project.id,is_active=True,sales_enabled=True,accepts_new_leads=True).first() is not None
    keys={'delivery':['delivery_dates'],'parking':['parking_and_storage'],'location':['country','city','timezone']}.get(task,[])
    states=project.profile.field_states or {}
    return any(data.get(key) not in (None,'',[],{}) or states.get(key,{}).get('status')=='not_applicable' for key in keys)


def transition(db,project,target,payload):
    from .models import ProjectProfile
    db.query(ProjectProfile).filter_by(id=project.profile.id).with_for_update().one()
    db.refresh(project.profile)
    bag=deepcopy((project.profile.field_sources or {}).get('__ui_deferrals__',{}))
    focus=(bag.get(FOCUS) or {}).get('draft') or {}
    revision=int(focus.get('revision',0))
    if payload.expected_navigation_revision!=revision:
        raise HTTPException(409,'The active review changed in another session. Refresh before switching sections.')
    source=payload.from_task
    if source is not None and source not in {*CARDS,'review','meta'}:raise HTTPException(422,'Unknown previous editor.')
    if focus.get('active_task') and source!=focus['active_task']:
        raise HTTPException(409,'The previous review is no longer current. Refresh before switching sections.')
    if len(json.dumps(payload.draft).encode())>200000 or _credentials(payload.draft):
        raise HTTPException(422,'Use a bounded onboarding draft without credentials or file bytes.')
    # Never accept another Project's IDs in a persisted catalog draft.
    if source=='catalog':
        allowed={row[0] for row in db.query(ProjectPropertyType.id).filter_by(project_id=project.id)}
        if not isinstance(payload.draft.get('items',[]),list):raise HTTPException(422,'Use a list of property drafts.')
        if any(not isinstance(item,dict) or item.get('id') not in allowed for item in payload.draft.get('items',[])):
            raise HTTPException(422,'A property draft does not belong to this Project.')
    now=datetime.utcnow().isoformat()
    for key,record in bag.items():
        if record.get('resumed') and key!=CARDS.get(target):record['resumed']=False
    if source in CARDS and source!=target:
        card=CARDS[source]; previous=bag.get(card,{})
        pending=payload.changed or previous.get('pending_draft',False) or not has_saved(db,project,source)
        bag[card]={**previous,'deferred':bool(pending),'resumed':False,
            'pending_draft':bool(payload.changed or previous.get('pending_draft',False)),
            'draft':payload.draft if payload.changed else previous.get('draft',{}),'updated_at':now}
    if target in CARDS:
        card=CARDS[target]
        if card in bag:bag[card]={**bag[card],'deferred':False,'resumed':True,'updated_at':now}
    bag[FOCUS]={'deferred':False,'resumed':False,'draft':{'active_task':target,'revision':revision+1},'updated_at':now}
    project.profile.field_sources={**(project.profile.field_sources or {}),'__ui_deferrals__':bag}
    flag_modified(project.profile,'field_sources')
    db.add(project.profile)
