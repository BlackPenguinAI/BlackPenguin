import unittest
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from scoped_policy import SCOPE, check_scope, check_input, check_policy, check_grant


class ScopedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.project=SimpleNamespace(id=SCOPE['project_id'],company_id=SCOPE['company_id'],is_demo=True,is_active=True)
        self.lead=SimpleNamespace(id=SCOPE['lead_id'],company_id=SCOPE['company_id'],project_id=SCOPE['project_id'],is_demo=True,is_test=True,is_opt_out=False,deleted_at=None,consent_status='granted_simulation',agent_status='paused')
        self.conv=SimpleNamespace(id=SCOPE['conversation_id'],company_id=SCOPE['company_id'],project_id=SCOPE['project_id'],lead_id=SCOPE['lead_id'],channel='simulation',provider='simulation',is_paused=False)
        self.policy={'published_version_id':'p','configuration':{'enabled':True,'model':'openai/gpt-4o-mini','provider':'openrouter','enabled_tools':['get_project_overview']},'engine_selection':{'hermes_live_ready':False}}
        self.grant={'active':True,'expires_at':self.now+timedelta(minutes=1),'policy_id':'p'}

    def test_exact_scope(self):check_scope(self.project,self.lead,self.conv)
    def test_other_company(self):
        self.conv.company_id='elsewhere'
        with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
    def test_other_project(self):
        self.lead.project_id='other'
        with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
    def test_live_channel(self):
        self.conv.channel='sms'
        with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
    def test_not_test_lead(self):
        self.lead.is_test=False
        with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
    def test_non_demo_project(self):
        self.project.is_demo=False
        with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
    def test_opt_out_human_and_pause(self):
        for obj,attr,value in [(self.lead,'is_opt_out',True),(self.lead,'agent_status','human_control'),(self.conv,'is_paused',True)]:
            old=getattr(obj,attr);setattr(obj,attr,value)
            with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
            setattr(obj,attr,old)
    def test_consent(self):
        self.lead.consent_status='unknown'
        with self.assertRaises(PermissionError):check_scope(self.project,self.lead,self.conv)
    def test_policy(self):self.assertEqual(check_policy(self.policy),'p')
    def test_native_effect_tools_rejected(self):
        for tool in ('book_onsite_visit','get_unit_media','update_lead_profile','cancel_onsite_visit'):
            self.policy['configuration']['enabled_tools']=['get_project_overview',tool]
            with self.assertRaises(PermissionError):check_policy(self.policy)
    def test_disabled_or_wrong_model(self):
        self.policy['configuration']['enabled']=False
        with self.assertRaises(PermissionError):check_policy(self.policy)
        self.policy['configuration'].update(enabled=True,model='other/model')
        with self.assertRaises(PermissionError):check_policy(self.policy)
    def test_production_gate(self):
        self.policy['engine_selection']['hermes_live_ready']=True
        with self.assertRaises(PermissionError):check_policy(self.policy)
    def test_grant(self):check_grant(self.grant,'p',self.now)
    def test_expiry_revocation_policy_change(self):
        for g,p in [({**self.grant,'active':False},'p'),({**self.grant,'expires_at':self.now},'p'),(self.grant,'different')]:
            with self.assertRaises(PermissionError):check_grant(g,p,self.now)
    def test_input(self):
        check_input('hermes:staged:one','Show me homes')
        for event,msg in [('sms:real','hello'),('hermes:staged:','hello'),('hermes:staged:one',' '),('hermes:staged:one','é'*2001)]:
            with self.assertRaises(PermissionError):check_input(event,msg)

if __name__=='__main__':unittest.main()
