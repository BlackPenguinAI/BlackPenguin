"""HEI-06B.1: authenticated SMS evidence quarantine, NOT a commercial ingress."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

PATH = '/webhooks/telnyx/messaging'
MAX_BODY = 32768
MAX_EVENTS = 1000
PHONE = re.compile(r'\+[1-9][0-9]{7,14}\Z')
DER_PREFIX = bytes.fromhex('302a300506032b6570032100')  # Ed25519 SubjectPublicKeyInfo

class Denied(Exception):
    def __init__(self, status):
        self.status = status


def need(condition, status=400):
    if not condition:
        raise Denied(status)


def uuid_text(value):
    need(isinstance(value, str))
    try:
        return str(UUID(value))
    except ValueError:
        raise Denied(400) from None


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result)
        result[key] = value
    return result


def parse_json(raw):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Denied(400)))
    except (ValueError, UnicodeError, RecursionError):
        raise Denied(400) from None
    need(isinstance(value, dict))
    return value


def decode64(value, length):
    try:
        decoded = base64.b64decode(value, validate=True)
        need(len(decoded) == length)
        return decoded
    except (ValueError, TypeError):
        raise Denied(400) from None


class Policy:
    def __init__(self, cfg):
        need(set(cfg) == {'public_key_base64','profile_id','organization_id','sender_number','test_numbers','fingerprint_key_hex'})
        self.key = decode64(cfg['public_key_base64'], 32)
        self.profile = uuid_text(cfg['profile_id'])
        self.organization = uuid_text(cfg['organization_id'])
        self.sender = cfg['sender_number']
        numbers = cfg['test_numbers']
        need(isinstance(self.sender, str) and PHONE.fullmatch(self.sender))
        need(isinstance(numbers,list) and 1 <= len(numbers) <= 5 and all(isinstance(n,str) and PHONE.fullmatch(n) for n in numbers))
        need(len(set(numbers)) == len(numbers) and self.sender not in numbers)
        self.test_numbers = frozenset(numbers)
        key = cfg['fingerprint_key_hex']
        need(isinstance(key,str) and re.fullmatch(r'[0-9a-f]{64}',key))
        self.fingerprint_key = bytes.fromhex(key)
        need(self.fingerprint_key != bytes(32))

    def fingerprint(self, namespace, raw):
        return hmac.new(self.fingerprint_key, namespace + b'\0' + raw, hashlib.sha256).hexdigest()

    def verify(self, raw, signature, timestamp, now=None):
        need(0 < len(raw) <= MAX_BODY, 413)
        need(isinstance(timestamp,str) and re.fullmatch(r'[0-9]{10}',timestamp), 401)
        need(abs((time.time() if now is None else now) - int(timestamp)) <= 300, 401)
        try:
            sig = decode64(signature,64)
        except Denied:
            raise Denied(401) from None
        # OpenSSL Ed25519 one-shot verification requires seekable message input.
        # Never put body, key, or signature into command arguments or logs.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'key').write_bytes(DER_PREFIX+self.key)
            (p/'data').write_bytes(timestamp.encode('ascii')+b'|'+raw)
            (p/'sig').write_bytes(sig)
            try:
                result = subprocess.run(['openssl','pkeyutl','-verify','-pubin','-keyform','DER','-inkey',str(p/'key'),'-rawin','-in',str(p/'data'),'-sigfile',str(p/'sig')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1,check=False)
            except (OSError,subprocess.TimeoutExpired):
                raise Denied(503) from None
        need(result.returncode == 0,401)
        data = parse_json(raw).get('data')
        need(isinstance(data,dict))
        need(data.get('event_type') == 'message.received' and data.get('record_type') == 'event',403)
        event = uuid_text(data.get('id'))
        payload = data.get('payload')
        need(isinstance(payload,dict))
        need(payload.get('direction') == 'inbound' and payload.get('type') == 'SMS' and payload.get('record_type') == 'message',403)
        need(uuid_text(payload.get('messaging_profile_id')) == self.profile and uuid_text(payload.get('organization_id')) == self.organization,403)
        src, dst = payload.get('from'), payload.get('to')
        need(isinstance(src,dict) and isinstance(dst,list) and len(dst)==1 and isinstance(dst[0],dict))
        source = src.get('phone_number')
        need(isinstance(source,str) and source in self.test_numbers and dst[0].get('phone_number') == self.sender,403)
        need(payload.get('media') in (None,[]) and not payload.get('cc'),403)
        message_id = uuid_text(payload.get('id'))
        body = payload.get('text')
        need(isinstance(body,str) and 0 < len(body) <= 1600)
        # Retry metadata (meta.attempt/delivered_to) may change. Fingerprint only
        # the business identity/content. No raw body, number, or UUID is stored.
        stable = json.dumps([event,message_id,self.profile,self.organization,source,self.sender,body],ensure_ascii=True,separators=(',',':')).encode()
        return self.fingerprint(b'event',event.encode()), self.fingerprint(b'content',stable)


class Journal:
    def __init__(self, path, policy):
        self.path = str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), tag TEXT NOT NULL)')
            tag = policy.fingerprint(b'journal',json.dumps([policy.key.hex(),policy.profile,policy.organization,policy.sender,sorted(policy.test_numbers)],separators=(',',':')).encode())
            db.execute('INSERT OR IGNORE INTO identity VALUES (1,?)',(tag,))
            need(db.execute('SELECT tag FROM identity WHERE singleton=1').fetchone() == (tag,),503)
            db.execute('CREATE TABLE IF NOT EXISTS evidence (event TEXT PRIMARY KEY, digest TEXT NOT NULL, accepted_at INTEGER NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=.5)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def record(self, event, digest):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest FROM evidence WHERE event=?',(event,)).fetchone()
            if row is not None:
                need(hmac.compare_digest(row[0],digest),409)
                return 'duplicate'
            need(db.execute('SELECT count(*) FROM evidence').fetchone()[0] < MAX_EVENTS,503)
            db.execute('INSERT INTO evidence VALUES (?,?,?)',(event,digest,int(time.time())))
        return 'quarantined'

    def count(self):
        with self.connect() as db:
            return db.execute('SELECT count(*) FROM evidence').fetchone()[0]


class Handler(BaseHTTPRequestHandler):
    server_version = 'BP-Staging'
    sys_version = ''
    def log_message(self,*args):
        pass  # No URLs, header values, numbers or body in logs.
    def respond(self,status,result):
        payload=json.dumps({'status':result},separators=(',',':')).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close')
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection=True
    def header(self,name):
        vals=self.headers.get_all(name,[])
        need(len(vals)==1,400 if name=='Content-Length' else 401)
        return vals[0]
    def do_POST(self):
        try:
            need(self.path==PATH,404)
            need(not self.headers.get_all('Transfer-Encoding') and not self.headers.get_all('Content-Encoding'),400)
            need(self.headers.get_content_type()=='application/json',415)
            length=self.header('Content-Length')
            need(re.fullmatch(r'[0-9]{1,6}',length))
            n=int(length);need(0<n<=MAX_BODY,413)
            raw=self.rfile.read(n);need(len(raw)==n)
            signature=self.header('telnyx-signature-ed25519');timestamp=self.header('telnyx-timestamp')
            event,digest=self.server.policy.verify(raw,signature,timestamp)
            result=self.server.journal.record(event,digest)
            self.respond(200,result)
        except Denied as exc:
            self.respond(exc.status,'denied')
        except (OSError,sqlite3.Error):
            self.respond(503,'unavailable')
        except Exception:
            self.respond(503,'unavailable')
    def do_GET(self):
        self.respond(404,'denied')
    do_HEAD=do_GET
    do_PUT=do_GET
    do_DELETE=do_GET
    do_PATCH=do_GET
    do_OPTIONS=do_GET


class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32
    def __init__(self,address,policy,journal,context):
        self.policy=policy;self.journal=journal;self.context=context
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(address,Handler)
    def get_request(self):
        conn,addr=super().get_request();conn.settimeout(3);return conn,addr
    def process_request(self,request,addr):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:super().process_request(request,addr)
        except BaseException:
            self.slots.release();raise
    def process_request_thread(self,request,addr):
        try:
            with self.context.wrap_socket(request,server_side=True) as tls:
                self.finish_request(tls,addr)
        except (OSError,ssl.SSLError):
            pass
        finally:
            self.shutdown_request(request);self.slots.release()
    def handle_error(self,*args):
        pass


def main():
    os.umask(0o077)
    need(os.geteuid()==10001 and os.getegid()==10001,503)
    cfg=Policy(parse_json(Path('/config/policy.json').read_bytes()))
    journal=Journal('/journal/evidence.sqlite3',cfg)
    if sys.argv[1:]==['stats']:
        print(json.dumps({'quarantined_unique_events':journal.count(),'commercial_ingress':'DISABLED','real_outbound':'DISABLED','production_readiness':'CLOSED'}));return
    need(not sys.argv[1:])
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain('/tls/fullchain.pem','/tls/privkey.pem')
    with Server(('0.0.0.0',8443),cfg,journal,context) as server:
        print('HEI06B1_QUARANTINE_READY',flush=True);server.serve_forever()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('HEI06B1_STARTUP_FAILURE '+type(exc).__name__,file=sys.stderr);raise SystemExit(1) from None
