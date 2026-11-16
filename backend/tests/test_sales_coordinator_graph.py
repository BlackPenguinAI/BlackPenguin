"""Candidate graph equivalence and bounded, pre-effect reconsideration."""
import asyncio,json,re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import httpx,pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_sales_booking_pilot import lab
from test_sales_continuity_repair1 import replay_provider
from test_sales_active_integration import understanding
from app.modules.sales_agent.coordinator_graph import execute,experiment,reconsider_reason,safe_candidate
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.db.postgres import Base
from app.core.config import settings
from tools.sales_ai.synthetic_fixtures import seed
from tools.sales_ai.continuity_battery import evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard

@pytest.mark.parametrize('mode',['classic','graph','graph-reconsider'])
def test_obsolete_engine_names_are_rejected(mode):
    with pytest.raises(ValueError,match='Only graph-observe'):
        with experiment(mode):
            raise AssertionError('An obsolete engine must never execute.')


def test_missing_observation_callback_cannot_silently_run_old_sequence():
    async def forbidden():raise AssertionError('No callback should run.')
    with pytest.raises(ValueError):
        asyncio.run(execute(None,interpret=forbidden,plan=forbidden,fulfill=forbidden,observe=None))

@pytest.mark.parametrize('text',['Do not send photos.','My friend said show me photos.','If I asked for photos, what then?'])
def test_negative_or_reported_messages_do_not_get_optional_reconsideration(text):
    assert reconsider_reason(understanding(text,'materials',confidence=0),text) is None


def test_reconsideration_cannot_broaden_actions_or_raise_confidence_in_code():
    original=understanding('Could I get those?','materials',confidence=0,subjects={0:'photos'})
    assert reconsider_reason(original,'Could I get those?')
    assert not safe_candidate(original,understanding('Could I get those?','appointment'))
    assert not safe_candidate(original,original)
    assert original.confidence==0

@pytest.mark.parametrize('text',['Can you show me pictures?','Could you send us images?','We would like to view blueprints.'])
def test_literal_material_recovery_is_a_scoped_read_with_original_confidence(lab,text):
    from types import SimpleNamespace
    from app.modules.sales_agent.dialogue_continuity import normalize,literal_material_read
    from app.modules.sales_agent.dialogue_store import Scope,save
    from app.modules.sales_agent.understanding_contract import DialogueState
    from app.modules.sales_agent.models import SalesConversation
    from app.modules.sales_crm.models import Lead
    db,manifest=lab;project=manifest['projects'][1];prop=project['properties'][0]
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Synthetic Read',phone='+15550104444',is_demo=True);db.add(lead);db.flush()
    conv=SalesConversation(company_id=lead.company_id,project_id=project['id'],lead_id=lead.id,channel='simulation',provider='simulation');db.add(conv);db.flush()
    scope=Scope(lead.company_id,project['id'],conv.id,lead.id)
    state=DialogueState(selected_property_type_id=prop['id']);save(db,scope,event_key='known',expected_revision=0,state=state);db.commit()
    u=understanding(text,'catalog',confidence=0)
    previous=SimpleNamespace(role='assistant',status='delivered',metadata_json={})
    fixed,_=normalize(u,text,state,previous)
    assert fixed.permits('materials') and fixed.confidence==0
    assert literal_material_read(db,scope,fixed,text)
    for negative in ('Do not send photos.','My friend said show me photos.','If I wanted photos?'):
        assert not literal_material_read(db,scope,fixed,negative)


def test_failed_optional_reconsideration_falls_back_without_any_action(lab):
    from app.modules.sales_agent.dialogue_continuity import focused_material_question
    from app.modules.sales_agent.understanding_contract import DialogueState
    text='Could I get those pictures?';u=understanding(text,'materials',confidence=0,subjects={0:'photos'})
    assert focused_material_question(u,text,DialogueState(selected_property_type_id='home'),{'property_types':[{'id':'home','property_type':'Alder Home'}]})=='Would you like photos of Alder Home?'
    assert u.confidence==0


@pytest.mark.parametrize('mode',['graph-observe'])
def test_cli_prepare_records_mode_without_contacting_a_model(mode,tmp_path):
    import subprocess,sys
    target=tmp_path/'prepared'
    run=subprocess.run([sys.executable,'-m','tools.sales_ai.synthetic_lab','--suite','continuity-battery',
        '--orchestrator',mode,'--prepare-only','--max-turns','10','--output',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stdout
    report=json.loads((target/'summary.json').read_text())
    assert report['coordinator_mode']==mode and report['provider_calls']==0


def test_cli_rejects_candidate_for_an_unrelated_suite_before_credential_read(tmp_path):
    import subprocess,sys
    run=subprocess.run([sys.executable,'-m','tools.sales_ai.synthetic_lab','--suite','needs-discovery',
        '--orchestrator','graph','--prepare-only','--output',str(tmp_path/'bad')],capture_output=True,text=True)
    assert run.returncode==2 and 'invalid choice' in run.stderr


@pytest.mark.parametrize('change',[None,'sales_model','configuration_sha256','commit'])
def test_comparator_rejects_changed_inputs_and_never_claims_integral_quality(tmp_path,change):
    import zipfile
    from tools.sales_ai.compare_graph_runs import compare
    base=dict(commit='same',version='same',sales_model='test/offline',configuration_sha256='same',configuration_version=8,
        cost_reporting_complete=True,coordinator_mode='classic',cases=[{'case':'same','checks':[{'status':'PASS'}],'turns':[{'checks':[]}],'meetings':[]}],provider_usage={'cost_usd':0.01})
    for name in ('reference','candidate'):
        r={**base,'coordinator_mode':'classic' if name=='reference' else 'graph-reconsider'}
        if name=='candidate' and change:r[change]='changed'
        with zipfile.ZipFile(tmp_path/(name+'.zip'),'w') as z:z.writestr('report.json',json.dumps(r));z.writestr('catalog.json','{}')
    r=compare(tmp_path/'reference.zip',tmp_path/'candidate.zip')
    assert r['status']==('NOT_COMPARABLE' if change else 'COMPARABLE')
    assert r['total_cost_usd']==0.02 and r['overall_dialogue_quality']=='NOT_EVALUATED' and r['decision']=='REVIEW_REQUIRED'
    if change is None:
        import subprocess,sys
        output=tmp_path/'comparison.zip'
        completed=subprocess.run([sys.executable,'-m','tools.sales_ai.compare_graph_runs','--reference',str(tmp_path/'reference.zip'),
            '--candidate',str(tmp_path/'candidate.zip'),'--output',str(output)],capture_output=True,text=True)
        assert completed.returncode==0,completed.stderr
        with zipfile.ZipFile(output) as z:
            assert set(z.namelist())=={'reference.zip','candidate.zip','comparison.json','comparison.md'}
            assert z.read('reference.zip')==(tmp_path/'reference.zip').read_bytes()

