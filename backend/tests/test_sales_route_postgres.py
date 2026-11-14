"""A transferred sender has exactly one active route under concurrent claims."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sqlalchemy.orm import Session
from test_sales_runtime_postgres import postgres_case
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead
from app.modules.system_settings.models import TelnyxCompanyConfig
from app.modules.sales_agent.models import SalesConversation
from app.modules.sales_agent.provider_routes import release_stale_conflict


def test_postgres_two_claimers_retire_once_and_keep_one_current_tenant_route(postgres_case):
    engine,(old_company_id,old_id,_)=postgres_case
    key='telnyx:+15550100002:+15550100001'
    with Session(engine) as db:
        old=db.get(SalesConversation,old_id);old.provider_thread_key=key
        company=Company(name='New sender owner');db.add(company);db.flush()
        project=Project(company_id=company.id,name='New project');db.add(project);db.flush()
        lead=Lead(company_id=company.id,project_id=project.id,full_name='Synthetic new lead',phone='+15550100001',source='manual',consent_status='granted');db.add(lead);db.flush()
        db.add(TelnyxCompanyConfig(company_id=company.id,from_phone_number='+15550100002',live_sms_enabled=True,verification_status='verified'))
        ids=company.id,project.id,lead.id;db.commit()
    barrier=Barrier(2)
    def claim(_):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            current=release_stale_conflict(db,thread_key=key,company_id=ids[0],provider='telnyx',channel='sms')
            if current is None:
                current=SalesConversation(company_id=ids[0],project_id=ids[1],lead_id=ids[2],provider='telnyx',channel='sms',provider_thread_key=key,is_paused=False);db.add(current);db.flush()
            identifier=current.id;db.commit();return identifier
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(claim,range(2)))
    assert len(set(results))==1
    with Session(engine) as db:
        old=db.get(SalesConversation,old_id)
        assert old.company_id==old_company_id and old.provider_thread_key is None and old.is_paused
        assert old.continuity_json['retired_provider_route']['provider_thread_key']==key
        assert db.query(SalesConversation).filter_by(provider_thread_key=key).one().company_id==ids[0]

    from tools.sales_ai.inspect_sender_route import inspect
    report=inspect(engine,sender='+15550100002',recipient='+15550100001',channel='sms')
    assert report['read_only'] and report['active_route_count']==1 and report['active_route_matches_current_owner']
    assert len(report['conversations'])==2
    assert sum(bool(r['retired_route']) for r in report['conversations'])==1
