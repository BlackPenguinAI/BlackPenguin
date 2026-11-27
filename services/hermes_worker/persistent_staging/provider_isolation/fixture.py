"""Synthetic signing fixtures for tests; never included in the gateway image."""
import base64
import json
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4


def run(*args):
    return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout


def setup(root):
    root=Path(root);root.mkdir(exist_ok=True)
    private=root/'signing.pem'
    run('openssl','genpkey','-algorithm','Ed25519','-out',str(private))
    der=run('openssl','pkey','-in',str(private),'-pubout','-outform','DER')
    cfg={'public_key_base64':base64.b64encode(der[-32:]).decode(),'profile_id':str(uuid4()),'organization_id':str(uuid4()),'sender_number':'+12025550101','test_numbers':['+12025550102'],'fingerprint_key_hex':secrets.token_hex(32)}
    (root/'policy.json').write_text(json.dumps(cfg))
    return cfg


def event(cfg):
    return {'data':{'id':str(uuid4()),'event_type':'message.received','record_type':'event','payload':{'id':str(uuid4()),'record_type':'message','direction':'inbound','type':'SMS','messaging_profile_id':cfg['profile_id'],'organization_id':cfg['organization_id'],'from':{'phone_number':cfg['test_numbers'][0]},'to':[{'phone_number':cfg['sender_number']}],'media':[],'text':'Synthetic property inquiry'}},'meta':{'attempt':1}}


def sign(root, value, timestamp=None):
    raw=value if isinstance(value,bytes) else json.dumps(value,separators=(',',':')).encode()
    stamp=str(int(time.time()) if timestamp is None else timestamp)
    data=Path(root)/'sign-input';data.write_bytes(stamp.encode()+b'|'+raw)
    signature=run('openssl','pkeyutl','-sign','-inkey',str(Path(root)/'signing.pem'),'-rawin','-in',str(data))
    return raw,base64.b64encode(signature).decode(),stamp


def certificate(root):
    root=Path(root)
    run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(root/'privkey.pem'),'-out',str(root/'fullchain.pem'))
