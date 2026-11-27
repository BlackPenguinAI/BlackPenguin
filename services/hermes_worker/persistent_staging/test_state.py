"""Host-side tests without Docker or application dependencies."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import sys
from guard import attest, DB, PURPOSE
import test_guard
from manage import read_state, KEYS

class Result:
    def __init__(self,rows):self.rows=rows
    def one(self):return self.rows[0]
    def all(self):return self.rows

class Connection:
    def __init__(self,marker,identity=(DB,DB,'160005')):self.marker=marker;self.identity=identity
    def execute(self,statement):
        return Result([self.identity] if 'current_database' in statement else [self.marker])

class StateTests(unittest.TestCase):
    def test_marker_and_candidate(self):
        env=test_guard.GuardTests().env()
        with patch.dict(os.environ,env,clear=True),patch.dict(sys.modules,{'sqlalchemy':SimpleNamespace(text=lambda x:x)}):
            self.assertEqual(attest(Connection((PURPOSE,'1'*64,'a'*40))),'a'*40)
            for marker in ((PURPOSE,'2'*64,'a'*40),(PURPOSE,'1'*64,'b'*40),('wrong','1'*64,'a'*40)):
                with self.assertRaises(PermissionError):attest(Connection(marker))
            with self.assertRaises(PermissionError):attest(Connection((PURPOSE,'1'*64,'a'*40),('production',DB,'160005')))
    def test_fresh_requires_explicit_bootstrap(self):
        with patch.dict(os.environ,test_guard.GuardTests().env(),clear=True),patch.dict(sys.modules,{'sqlalchemy':SimpleNamespace(text=lambda x:x)}):
            conn=Connection((PURPOSE,'1'*64,None))
            with self.assertRaises(PermissionError):attest(conn)
            self.assertIsNone(attest(conn,allow_fresh=True))
    def test_state_is_not_shell_input(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);d.chmod(0o700);p=d/'staging.env'
            data=''.join(f'{key}={str(i)*64}\n' for i,key in enumerate(KEYS,1))+'STAGE_COMMIT='+'a'*40+'\n'
            p.write_text(data);p.chmod(0o600)
            self.assertEqual(read_state(d)['STAGE_COMMIT'],'a'*40)
            p.write_text(data+'COMPOSE_FILE=/production.yml\n')
            with self.assertRaises(ValueError):read_state(d)
            p.write_text(data);p.chmod(0o644)
            with self.assertRaises(ValueError):read_state(d)

if __name__=='__main__':unittest.main()
