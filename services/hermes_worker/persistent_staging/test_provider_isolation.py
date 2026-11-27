import copy
import http.client
import json
from pathlib import Path
import ssl
import tempfile
import threading
import time
import unittest
from provider_isolation import fixture, receiver
from permanent import topology, state_directory


class ProviderIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.cfg=fixture.setup(cls.root);fixture.certificate(cls.root)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.policy=receiver.Policy(self.cfg);self.data=fixture.event(self.cfg)
    def verify(self,value=None,stamp=None):
        return self.policy.verify(*fixture.sign(self.root,self.data if value is None else value,stamp))
    def deny(self,code,value=None,stamp=None):
        with self.assertRaises(receiver.Denied) as result:self.verify(value,stamp)
        self.assertEqual(result.exception.status,code)
    def test_valid_signature(self):self.assertEqual(tuple(map(len,self.verify())),(64,64))
    def test_tamper(self):
        raw,sig,stamp=fixture.sign(self.root,self.data)
        with self.assertRaises(receiver.Denied) as cm:self.policy.verify(raw+b' ',sig,stamp)
        self.assertEqual(cm.exception.status,401)
    def test_missing_signature(self):
        raw,_,stamp=fixture.sign(self.root,self.data)
        with self.assertRaises(receiver.Denied) as cm:self.policy.verify(raw,None,stamp)
        self.assertEqual(cm.exception.status,401)
    def test_expired(self):self.deny(401,stamp=int(time.time())-301)
    def test_future(self):self.deny(401,stamp=int(time.time())+301)
    def test_wrong_profile(self):self.data['data']['payload']['messaging_profile_id']='00000000-0000-4000-8000-000000000001';self.deny(403)
    def test_wrong_organization(self):self.data['data']['payload']['organization_id']='00000000-0000-4000-8000-000000000001';self.deny(403)
    def test_wrong_sender(self):self.data['data']['payload']['from']['phone_number']='+12025550199';self.deny(403)
    def test_wrong_recipient(self):self.data['data']['payload']['to'][0]['phone_number']='+12025550199';self.deny(403)
    def test_multiple_recipients(self):self.data['data']['payload']['to']*=2;self.deny(400)
    def test_media(self):self.data['data']['payload']['media']=[{'url':'https://example.invalid'}];self.deny(403)
    def test_callback(self):self.data['data']['event_type']='message.finalized';self.deny(403)
    def test_duplicate_json_key(self):self.deny(400,b'{"data":{},"data":{}}')
    def test_retry_meta(self):
        a=self.verify();self.data['meta']['attempt']=2;self.assertEqual(a,self.verify())
    def test_persistence_conflict_privacy(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.db';a=receiver.Journal(path,self.policy);event,digest=self.verify()
            self.assertEqual(a.record(event,digest),'quarantined');b=receiver.Journal(path,self.policy)
            self.assertEqual(b.record(event,digest),'duplicate');self.assertEqual(b.count(),1)
            self.data['data']['payload']['text']='Changed';event,new_digest=self.verify()
            with self.assertRaises(receiver.Denied) as cm:b.record(event,new_digest)
            self.assertEqual(cm.exception.status,409);self.assertEqual(b.count(),1)
            self.assertNotIn(b'Synthetic property inquiry',path.read_bytes());self.assertNotIn(self.cfg['test_numbers'][0].encode(),path.read_bytes())
    def test_journal_policy_change(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.db';receiver.Journal(path,self.policy)
            cfg=copy.deepcopy(self.cfg);cfg['test_numbers']=['+12025550199']
            with self.assertRaises(receiver.Denied):receiver.Journal(path,receiver.Policy(cfg))
    def test_extra_config_key(self):
        cfg={**self.cfg,'TELNYX_API_KEY':'not-allowed'}
        with self.assertRaises(receiver.Denied):receiver.Policy(cfg)
    def test_tls_http_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            journal=receiver.Journal(Path(td)/'j.db',self.policy)
            ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(self.root/'fullchain.pem',self.root/'privkey.pem')
            with receiver.Server(('127.0.0.1',0),self.policy,journal,ctx) as server:
                t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
                def request(method,path,raw=None,headers=None):
                    client=http.client.HTTPSConnection('127.0.0.1',server.server_port,context=ssl.create_default_context(cafile=str(self.root/'fullchain.pem')),timeout=5)
                    try:
                        client.request(method,path,body=raw,headers=headers or {});response=client.getresponse();return response.status,json.loads(response.read())
                    finally:client.close()
                try:
                    raw,sig,stamp=fixture.sign(self.root,self.data);headers={'Content-Type':'application/json','telnyx-signature-ed25519':sig,'telnyx-timestamp':stamp}
                    self.assertEqual(request('GET','/api/v1/auth/login')[0],404)
                    self.assertEqual(request('POST',receiver.PATH,raw,{'Content-Type':'application/json'})[0],401)
                    self.assertEqual(request('POST',receiver.PATH,raw,headers),(200,{'status':'quarantined'}))
                    self.assertEqual(request('POST',receiver.PATH,raw,headers),(200,{'status':'duplicate'}))
                    self.assertEqual(journal.count(),1)
                finally:server.shutdown();t.join(3)
    def test_topology_rejects_private_network_join(self):
        obj={'Config':{'Labels':{'com.docker.compose.project':'test','com.docker.compose.service':'receiver'},'User':'10001:10001'},'State':{'Running':True},'NetworkSettings':{'Networks':{'test_quarantine':{},'bp_private':{}},'Ports':{'8443/tcp':[{'HostIp':'127.0.0.1','HostPort':'18443'}]}}}
        with self.assertRaises(ValueError):topology(obj,'test','receiver',{'test_quarantine'},{('8443/tcp','127.0.0.1','18443')},'10001:10001')
    def test_relative_state_denied(self):
        with self.assertRaises(ValueError):state_directory(Path('relative'))
