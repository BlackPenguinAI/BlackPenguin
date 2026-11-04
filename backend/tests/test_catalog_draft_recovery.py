from copy import deepcopy
import pytest
from fastapi import HTTPException
from test_onboarding_revisions_and_money import context
from app.modules.projects import catalog_service
from app.modules.onboarding_deferrals import records
from app.modules.governance.models import PlatformAuditEvent


def pending(context):
    db,company,user,project,profile,item=context
    profile.field_sources={**(profile.field_sources or {}),'__ui_deferrals__':{
        'property:'+item.id:{'resumed':True,'draft':{'name':'Pending name'}},
        'field:property_type_catalog':{'resumed':True,'draft':{'items':[{'id':item.id,'name':'Pending name'},{'id':'other','name':'Other pending'}],'newType':{'name':'Uncreated draft'}}},
    }}
    db.commit();return db,user,project,profile,item


def test_scalar_save_resolves_only_the_saved_catalog_row(context):
    db,user,project,profile,item=pending(context)
    count=db.query(PlatformAuditEvent).count()
    published=deepcopy(profile.published_snapshot)
    catalog_service.update(db,project,item,{'name':'Final name'},user_id=user.id)
    saved=records(profile)
    assert saved['property:'+item.id]['draft']=={}
    assert saved['field:property_type_catalog']['draft']['items']==[{'id':'other','name':'Other pending'}]
    assert saved['field:property_type_catalog']['draft']['newType']=={'name':'Uncreated draft'}
    assert db.query(PlatformAuditEvent).count()>count
    assert profile.published_snapshot==published


def test_failed_scalar_save_does_not_discard_pending_drafts(context):
    db,user,project,profile,item=pending(context)
    previous=deepcopy(records(profile))
    with pytest.raises(HTTPException):catalog_service.update(db,project,item,{'name':' '},user_id=user.id)
    db.rollback();db.refresh(profile)
    assert records(profile)==previous


def test_plain_or_unrelated_deferrals_are_preserved(context):
    db,company,user,project,profile,item=context
    profile.field_sources={**(profile.field_sources or {}),'__ui_deferrals__':{'team':{'deferred':True,'draft':{'note':'Keep'}}}}
    db.commit()
    catalog_service.update(db,project,item,{'description':'New description'},user_id=user.id)
    assert records(profile)['team']=={'deferred':True,'draft':{'note':'Keep'}}
