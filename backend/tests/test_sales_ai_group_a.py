"""Group A infrastructure checks, not acceptance of the future sales journey."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from sales_ai_support.adapters import FakeCalendar, RecordingMessenger, ScriptedModel
from sales_ai_support.clock import FrozenClock
from sales_ai_support.sandbox import FIXTURES, Sandbox, InboundHarness, load_catalog
from sales_ai_support.trace import TurnTrace
from tools.sales_ai.export_context import export_project_context
from tools.sales_ai.snapshot import BASE_COMMIT, build_catalog, read_snapshot
from tools.sales_ai.replay import interpretation, run_case


@pytest.fixture
def real():return load_catalog()


@pytest.fixture
def synthetic():return load_catalog('synthetic_catalog.json')


@pytest.fixture
def sandbox(synthetic):
    value=Sandbox(synthetic)
    yield value
    value.close()


def test_real_catalog_keeps_provenance_and_does_not_invent_missing_inventory(real):
    assert real['source_commit']==BASE_COMMIT
    captured=datetime.fromisoformat(real['captured_at'])
    assert captured.tzinfo is not None and captured.date().isoformat()=='2026-11-08'
    assert len(real['projects'])==6
    assert {p['origin'] for p in real['projects']}=={'REAL_APPROVED','EXPORTED_DEMO'}
    assert sum(len(p['units']) for p in real['projects'])==0
    trails=next(p for p in real['projects'] if p['project']['name']=='The Trails')
    assert trails['approval']['revision']==31
    ashville=next(p for p in real['projects'] if p['project']['name']=='Ashville Park')
    assert ashville['approval']['revision']==27
    assert len(ashville['property_types'])==1
    assert all(a['content_verified'] is False for p in real['projects'] for a in p['materials'])


def test_synthetic_answers_appointments_and_materials_are_explicit(synthetic):
    assert all(p['origin']=='SYNTHETIC' for p in synthetic['projects'])
    assert {len(p['property_types']) for p in synthetic['projects']}=={1,3}
    assert synthetic['synthetic_meta_answers']['profile_facts']['budget']['source']=='SYNTHETIC_META'
    assert {v['key'] for v in synthetic['synthetic_appointment_variants']}=={'active','past','cancelled'}
    assert len(synthetic['specialists'])==2
    assert len({u['timezone'] for u in synthetic['specialists']})==2


def test_disposable_loader_enforces_scope_and_uses_no_production_engine(real):
    from app.db.postgres import engine as configured_engine
    from app.modules.projects.models import Project
    from app.modules.sales_agent.commercial_context import build_commercial_context
    value=Sandbox(real)
    try:
        assert value.engine is not configured_engine and str(value.engine.url)=='sqlite:///:memory:'
        assert value.db.execute(text('PRAGMA foreign_keys')).scalar_one()==1
        for p in value.db.query(Project):
            context=build_commercial_context(value.db,project=p,company_id=p.company_id,lead_id='unused-offline',channel='sms')
            expected=next(x for x in real['projects'] if x['project']['id']==p.id)
            assert {t['id'] for t in context['property_types']}=={t['id'] for t in expected['property_types']}
            assert context['approved_revision']==expected['approval']['revision']
            with pytest.raises(ValueError):
                build_commercial_context(value.db,project=p,company_id='another-company',lead_id='unused',channel='sms')
    finally:value.close()


def test_clock_controls_timezone_and_requires_monotonic_aware_evidence(monkeypatch):
    from zoneinfo import ZoneInfo
    clock=FrozenClock()
    module=SimpleNamespace(datetime=datetime)
    clock.install(monkeypatch,module)
    assert module.datetime.utcnow()==datetime(2026,11,8,13,23,42)
    assert clock.now(ZoneInfo('America/New_York')).hour==8
    clock.advance(minutes=45)
    assert module.datetime.now(timezone.utc).minute==8
    with pytest.raises(ValueError):clock.advance(seconds=-1)
    with pytest.raises(ValueError):FrozenClock(datetime(2026,11,8))


def test_calendar_fake_intersections_idempotency_and_failure_are_explicit():
    calendar=FakeCalendar();start=FrozenClock().now();end=start+timedelta(minutes=45)
    first=calendar.create('sales-a',start,end,key='one')
    assert calendar.create('sales-a',start,end,key='one')==first
    assert len(calendar.events)==1
    with pytest.raises(ValueError):calendar.create('sales-a',start,end,key='two')
    assert calendar.create('sales-b',start,end,key='other-sales')
    calendar.failures.append(TimeoutError('SYNTHETIC Calendar timeout'))
    with pytest.raises(TimeoutError):calendar.delete('one')
    assert 'one' in calendar.events
    calendar.delete('one');calendar.delete('one')
    assert not calendar.busy('sales-a',start,end)
    with pytest.raises(ValueError):calendar.busy('sales-a',start.replace(tzinfo=None),end)


def test_provider_acceptance_is_not_a_delivery_receipt():
    sender=RecordingMessenger()
    result=asyncio.run(sender(channel='whatsapp',content='SYNTHETIC',db=object(),auth_token='must-not-be-recorded'))
    assert result['status']=='sent' and sender.receipts[result['sid']]=='sent'
    assert sender.calls[0]['kwargs']['auth_token']=='[redacted]'
    sender.receipt(result['sid'])
    assert sender.receipts[result['sid']]=='delivered'
    sender.failures.append(TimeoutError('SYNTHETIC provider timeout'))
    with pytest.raises(TimeoutError):asyncio.run(sender(content='Not accepted'))
    assert len(sender.calls)==1


def test_scripted_model_fails_instead_of_using_an_unconfigured_provider():
    model=ScriptedModel({'result':'test'},TimeoutError('SYNTHETIC timeout'))
    assert json.loads(asyncio.run(model('model',[],{})))=={'result':'test'}
    with pytest.raises(TimeoutError):asyncio.run(model('model',[],{}))
    with pytest.raises(AssertionError):asyncio.run(model('model',[],{}))


def test_versioned_trace_is_scoped_ordered_and_excludes_secret_keys():
    clock=FrozenClock()
    trace=TurnTrace(clock,'c','p','l','conversation','inbound','run',BASE_COMMIT)
    payload={'approved_revision':27}
    trace.record('context',status='ok',evidence=payload)
    payload['approved_revision']=999
    assert trace.export()['events'][0]['evidence']['approved_revision']==27
    clock.advance(seconds=1)
    trace.record('tool',status='failed',evidence={'error_code':'TimeoutError','retryable':True})
    for payload in ({'nested':{'access_token':'secret'}},{'chain_of_thought':'private'}):
        with pytest.raises(ValueError):trace.record('understanding',status='ok',evidence=payload)
    trace.record('complete',status='ok')
    assert [e['sequence'] for e in trace.export()['events']]==[1,2,3]
    assert trace.export()['configuration_version'] is None
    with pytest.raises(ValueError):trace.record('tool',status='ok')


def snapshot_file(tmp_path, *, malformed=None):
    records=[{'kind':'manifest','schema':{'companies':{'present':True}}},
             {'kind':'row','table':'companies','data':{'id':'company'}},
             {'kind':'table_end','table':'companies','row_count':1,'snapshot_count':1},
             {'kind':'complete','row_counts':{'companies':1},'total_rows':1}]
    if malformed=='missing_footer':records.pop()
    if malformed=='wrong_count':records[-1]['total_rows']=2
    if malformed=='after_complete':records.append(records[1])
    path=tmp_path/'snapshot.jsonl.gz'
    with gzip.open(path,'wt') as stream:
        for row in records:stream.write(json.dumps(row)+'\n')
    return path


@pytest.mark.parametrize('malformed',['missing_footer','wrong_count','after_complete'])
def test_importer_rejects_partial_or_corrupt_snapshot(tmp_path,malformed):
    with pytest.raises(ValueError):read_snapshot(snapshot_file(tmp_path,malformed=malformed))


def test_importer_verifies_full_snapshot_counts(tmp_path):
    _,rows,footer=read_snapshot(snapshot_file(tmp_path))
    assert len(rows['companies'])==footer['total_rows']==1


def test_scoped_export_reads_approved_version_without_leads_or_secret_columns(sandbox):
    pid=sandbox.catalog['projects'][0]['project']['id']
    statements=[]
    @event.listens_for(sandbox.engine,'before_cursor_execute')
    def observe(c,cursor,statement,params,context,many):statements.append(statement)
    result=export_project_context(sandbox.engine,[pid])
    assert len(result['projects'])==1 and result['projects'][0]['project']['id']==pid
    assert result['projects'][0]['approval']['revision']==1
    assert result['export_scope']['database_read_only'] is True
    assert result['export_scope']['leads_exported']==result['export_scope']['messages_exported']==0
    assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','ALTER','CREATE','DROP')) for s in statements)
    business_selects=[s.lower() for s in statements if s.lstrip().upper().startswith('SELECT') and 'sqlite_master' not in s]
    assert not any('"leads"' in s or '"sales_messages"' in s or 'ciphertext' in s or 'hashed_password' in s for s in business_selects)
    assert result['integration_status']['live_probes_performed'] is False
    assert {u['id'] for u in result['specialists']}=={a['user_id'] for a in result['assignments']}


def test_scoped_export_bounds_recorded_meetings_without_exposing_leads(sandbox):
    from app.modules.sales_crm.models import Meeting
    pid=sandbox.catalog['projects'][0]['project']['id']
    _,lead,_=sandbox.conversation(pid,'sms')
    uid=sandbox.catalog['specialists'][0]['id']
    now=sandbox.clock.utcnow()
    sandbox.db.add_all([
        Meeting(project_id=pid,lead_id=lead.id,assigned_sales_user_id=uid,meeting_time=now-timedelta(minutes=10),duration_minutes=45,notes='PRIVATE_NOTE'),
        Meeting(project_id=pid,lead_id=lead.id,assigned_sales_user_id=uid,meeting_time=now-timedelta(days=20),duration_minutes=45),
        Meeting(project_id=pid,lead_id=lead.id,assigned_sales_user_id=uid,meeting_time=now+timedelta(days=50),duration_minutes=45)])
    sandbox.db.commit()
    result=export_project_context(sandbox.engine,[pid],now=sandbox.clock.now())
    assert len(result['recorded_meeting_intervals'])==1
    assert 'PRIVATE_NOTE' not in json.dumps(result,default=str)
    assert 'lead_id' not in result['recorded_meeting_intervals'][0]


def test_scoped_export_preserves_published_data_over_draft_changes(sandbox):
    from app.modules.projects.models import ProjectProfile
    profile=sandbox.db.query(ProjectProfile).first()
    profile.profile_data={**profile.profile_data,'short_description':'UNAPPROVED_DRAFT_ONLY'}
    sandbox.db.commit()
    result=export_project_context(sandbox.engine,[profile.project_id],now=sandbox.clock.now())
    assert result['projects'][0]['approval']['source']=='published_snapshot'
    assert 'UNAPPROVED_DRAFT_ONLY' not in json.dumps(result,default=str)


def test_scoped_export_rejects_unknown_or_unapproved_project(sandbox):
    with pytest.raises(ValueError):export_project_context(sandbox.engine,['not-a-project'])
    # Reset the connection-local SQLite read-only flag before modifying a test fixture.
    sandbox.db.execute(text('PRAGMA query_only=OFF'))
    from app.modules.projects.models import ProjectProfile
    profile=sandbox.db.query(ProjectProfile).first()
    profile.published_snapshot=None;profile.final_approved=False;sandbox.db.commit()
    with pytest.raises(ValueError):export_project_context(sandbox.engine,[profile.project_id])


def test_import_scope_validation_cannot_turn_another_company_catalog_into_facts(synthetic):
    entry=synthetic['projects'][0]
    rows={'companies':[{'id':entry['project']['company_id']}],'projects':[entry['project']],
          'project_profiles':[{'id':entry['approval']['profile_id'],'project_id':entry['project']['id'],
                               'final_approved':True,'published_snapshot':{'profile_id':entry['approval']['profile_id'],
                               'company_id':'wrong-company','states':{},'data':{}}}]}
    with pytest.raises(ValueError):build_catalog({},rows)


def test_target_matrix_is_complete_but_does_not_claim_future_acceptance():
    matrix=json.loads((FIXTURES/'acceptance_matrix.json').read_text())
    assert [c['id'] for c in matrix['cases']]==[f'T{i:02d}' for i in range(1,27)]
    configured_root=os.environ.get('SALES_ACCEPTANCE_ROOT')
    root=Path(configured_root) if configured_root is not None else Path(__file__).resolve().parents[2]
    assert root.is_absolute(), 'SALES_ACCEPTANCE_ROOT must be an absolute path.'
    assert root.is_dir(), f'Acceptance reference root is missing: {root}'
    for case in matrix['cases']:
        assert case['required_outcomes'] and case['forbidden_outcomes']
        assert case['acceptance_status']=='PENDING_NEW_FLOW'
        assert case['channels']==['sms','whatsapp']
        for path in case['existing_partial_regressions']:assert (root/path).is_file()


def test_historical_evidence_does_not_invent_missing_stack_or_current_reproduction():
    history=json.loads((FIXTURES/'historical_cases_20261108.json').read_text())
    assert len(history['cases'])==6
    assert all(c['origin']=='HISTORICAL_OBSERVATION' for c in history['cases'])
    assert history['cases'][0]['intent_contract_issues']==['missing_or_invalid_confidence']
    assert history['cases'][-1]['observed_error_code']=='IntegrityError'
    assert all(c['acceptance_status']=='PENDING_NEW_FLOW' for c in history['cases'])


@pytest.mark.parametrize('channel',['sms','whatsapp'])
@pytest.mark.parametrize('case_id',['H01','H02','H03','H04','H05','H06'])
def test_current_coordinator_replays_reviewed_text_without_pause_or_booking(real,monkeypatch,case_id,channel):
    history=json.loads((FIXTURES/'historical_cases_20261108.json').read_text())
    case=next(c for c in history['cases'] if c['id']==case_id)
    result=run_case(real,case['project_id'],channel,case['inbound'],[interpretation(case['inbound'])],
                    case_id=case_id,origin='SCRIPTED_REPLAY_OF_HISTORICAL_TEXT',monkeypatch=monkeypatch)
    assert result['passed_current_safety'], result['failures']
    assert result['model_quality_evaluated'] is False and result['new_flow_acceptance']=='PENDING'


@pytest.mark.parametrize('channel',['sms','whatsapp'])
@pytest.mark.parametrize('failure',['invalid_json','timeout'])
def test_current_coordinator_model_failure_keeps_response_and_deduplicates(synthetic,monkeypatch,channel,failure):
    responses=['invalid JSON']*2 if failure=='invalid_json' else [TimeoutError('SYNTHETIC timeout')]*2
    result=run_case(synthetic,synthetic['projects'][0]['project']['id'],channel,'Give me information',responses,
                    case_id=failure,origin='SYNTHETIC_FAILURE',monkeypatch=monkeypatch)
    assert result['passed_current_safety'], result['failures']


def test_sandbox_prevents_fallback_network_connection(sandbox,monkeypatch):
    import socket
    harness=InboundHarness(sandbox,sandbox.catalog['projects'][0]['project']['id'],'sms',monkeypatch)
    with harness.boundaries(),pytest.raises(AssertionError):
        socket.create_connection(('example.invalid',443))


def test_calendar_boundary_uses_fake_busy_data_and_synthetic_provider_event(sandbox,monkeypatch):
    from app.modules.sales_crm import scheduling
    from app.integrations import gcalendar_client
    harness=InboundHarness(sandbox,sandbox.catalog['projects'][0]['project']['id'],'sms',monkeypatch)
    uid=sandbox.catalog['specialists'][0]['id']
    connection=SimpleNamespace(user_id=uid)
    start=sandbox.clock.now();end=start+timedelta(minutes=45)
    with harness.boundaries():
        response=gcalendar_client.create_calendar_event_for_connection(sandbox.db,connection,
            start_time=start.replace(tzinfo=None),end_time=end.replace(tzinfo=None),event_id='fixture-key')
        assert response['id']=='offline-calendar-fixture-key'
        assert scheduling.calendar_busy_ranges(sandbox.db,connection,starts_at=start,ends_at=end)
        assert not scheduling.is_calendar_free(sandbox.db,connection,starts_at=start,ends_at=end)
        gcalendar_client.delete_calendar_event_for_connection(sandbox.db,connection,response['id'])
        assert scheduling.is_calendar_free(sandbox.db,connection,starts_at=start,ends_at=end)
