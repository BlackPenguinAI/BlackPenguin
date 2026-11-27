"""Focused denial tests, runnable without Docker or backend dependencies."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
import unittest

from live_scope_policy import *


class LiveScopeTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.cap=Capability('first','generation','policy')
        self.row={**SCOPE,'active':True,'generation':'generation','policy_id':'policy',
                  'expires_at':self.now+timedelta(minutes=5),'active_job':self.cap.job_id}
        self.snapshot={'published_version_id':'policy','configuration':{'enabled':True,'enabled_tools':list(TOOLS),'provider':'openrouter','model':'openai/gpt-4o-mini'},'engine_selection':{'active_sales_engine':'langgraph','hermes_live_ready':False}}
        self.company=NS(id=SCOPE['company_id'],name=COMPANY_NAME,is_active=True)
        self.project=NS(id=SCOPE['project_id'],company_id=self.company.id,name=PROJECT_NAME,is_active=True,is_demo=False)
        self.lead=NS(id=SCOPE['lead_id'],company_id=self.company.id,project_id=self.project.id,full_name=LEAD_NAME,phone=PHONE,is_test=True,is_demo=False,deleted_at=None,is_opt_out=False,consent_status='granted',agent_status='active')
        self.conv=NS(id=SCOPE['conversation_id'],company_id=self.company.id,project_id=self.project.id,lead_id=self.lead.id,provider='telnyx',channel='sms',provider_thread_key=None,is_paused=False)
        self.job=NS(id=self.cap.job_id,conversation_id=self.conv.id,message_id=self.cap.inbound_id,status='processing')
        self.inbound=NS(id=self.cap.inbound_id,conversation_id=self.conv.id,provider_message_id=provider_id('first'),content=MESSAGES['first'],channel='sms',direction='inbound',role='user',metadata_json={'hei06a2b2_synthetic':MARKER,'hei06a2b2_generation':'generation','lead_id':self.lead.id,'project_id':self.project.id,'continuity_recorded':True})
    def test_valid_capability(self):self.assertEqual(check_capability(self.row,self.cap,'policy',self.now),self.cap)
    def test_no_capability(self):
        with self.assertRaises(ScopedDenied):check_capability(self.row,None,'policy',self.now)
    def test_revoked(self):
        with self.assertRaises(ScopedDenied):check_capability({**self.row,'active':False},self.cap,'policy',self.now)
    def test_expired(self):
        with self.assertRaises(ScopedDenied):check_capability({**self.row,'expires_at':self.now},self.cap,'policy',self.now)
    def test_other_generation(self):
        with self.assertRaises(ScopedDenied):check_capability({**self.row,'generation':'other'},self.cap,'policy',self.now)
    def test_other_policy(self):
        with self.assertRaises(ScopedDenied):check_capability(self.row,self.cap,'other',self.now)
    def test_other_scope(self):
        for k in SCOPE:
            with self.subTest(k=k),self.assertRaises(ScopedDenied):check_capability({**self.row,k:'other'},self.cap,'policy',self.now)
    def test_other_job(self):
        with self.assertRaises(ScopedDenied):check_capability(self.row,Capability('second','generation','policy'),'policy',self.now)
    def test_only_fixed_cases(self):
        with self.assertRaises(ScopedDenied):job_id('arbitrary')
    def test_policy(self):self.assertEqual(policy_id(self.snapshot),'policy')
    def test_policy_extra_tool(self):
        self.snapshot['configuration']['enabled_tools'].append('book_onsite_visit')
        with self.assertRaises(ScopedDenied):policy_id(self.snapshot)
    def test_policy_global_gate(self):
        self.snapshot['engine_selection']['active_sales_engine']='hermes'
        with self.assertRaises(ScopedDenied):policy_id(self.snapshot)
    def test_entities(self):check_entities(self.company,self.project,self.lead,self.conv)
    def test_actual_or_opted_out_lead(self):
        for k,v in [('is_test',False),('is_opt_out',True),('agent_status','human_control'),('phone','+123'),('consent_status','unknown')]:
            with self.subTest(k=k),self.assertRaises(ScopedDenied):check_entities(self.company,self.project,NS(**{**vars(self.lead),k:v}),self.conv)
    def test_other_conversation(self):
        for k,v in [('channel','whatsapp'),('provider','other'),('is_paused',True),('provider_thread_key','real-route')]:
            with self.subTest(k=k),self.assertRaises(ScopedDenied):check_entities(self.company,self.project,self.lead,NS(**{**vars(self.conv),k:v}))
    def test_inbound(self):check_inbound(self.job,self.inbound,self.cap)
    def test_arbitrary_message(self):
        self.inbound.content='different'
        with self.assertRaises(ScopedDenied):check_inbound(self.job,self.inbound,self.cap)
    def test_no_proof(self):
        self.inbound.metadata_json.pop('continuity_recorded')
        with self.assertRaises(ScopedDenied):check_inbound(self.job,self.inbound,self.cap)
    def test_pending_job_not_preparable(self):
        self.job.status='pending'
        with self.assertRaises(ScopedDenied):check_inbound(self.job,self.inbound,self.cap)
    def test_delivery(self):check_delivery(self.cap,SCOPE['company_id'],'telnyx',PHONE,'test')
    def test_real_recipient_denied(self):
        with self.assertRaises(ScopedDenied):check_delivery(self.cap,SCOPE['company_id'],'telnyx','+123','test')
    def test_revoked_case_no_delivery(self):
        with self.assertRaises(ScopedDenied):check_delivery(Capability('revoked','generation','policy'),SCOPE['company_id'],'telnyx',PHONE,'test')
    def test_task_capability_resets(self):
        from live_scope_runtime import bind,CURRENT
        self.assertIsNone(CURRENT.get())
        with self.assertRaises(RuntimeError):
            with bind(self.cap):
                self.assertEqual(CURRENT.get(),self.cap)
                raise RuntimeError('stop')
        self.assertIsNone(CURRENT.get())
    def test_no_context_uses_original_gate(self):
        from live_scope_runtime import active_gate
        def original(engine):raise RuntimeError('closed')
        def never_session():raise AssertionError('DB not touched without capability')
        with self.assertRaisesRegex(RuntimeError,'closed'):active_gate(original,never_session)('hermes')

if __name__=='__main__':unittest.main()
