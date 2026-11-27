"""Exercise the staging storage preflight without Docker or app dependencies."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from entrypoint import _check_upload_root, check_api_storage


class ApiStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'uploads'
        self.root.mkdir(mode=0o700)
        self.uid, self.gid = self.root.stat().st_uid, self.root.stat().st_gid

    def test_real_write_and_repeat(self):
        for _ in range(2):
            _check_upload_root(self.root, self.uid, self.gid)
        self.assertTrue((self.root / 'receipts').is_dir())
        self.assertEqual(list((self.root / 'receipts').iterdir()), [])

    def test_missing_mount(self):
        self.root.rmdir()
        with self.assertRaises(PermissionError):
            _check_upload_root(self.root, self.uid, self.gid)

    def test_wrong_permissions_or_owner(self):
        self.root.chmod(0o755)
        with self.assertRaises(PermissionError):
            _check_upload_root(self.root, self.uid, self.gid)
        self.root.chmod(0o700)
        with self.assertRaises(PermissionError):
            _check_upload_root(self.root, self.uid + 1, self.gid)

    def test_reject_receipt_symlink(self):
        (self.root / 'receipts').symlink_to(self.tmp.name, target_is_directory=True)
        with self.assertRaises(PermissionError):
            _check_upload_root(self.root, self.uid, self.gid)

    def test_reject_wrong_workdir_or_root_identity(self):
        with patch('pathlib.Path.cwd', return_value=Path('/wrong')):
            with self.assertRaises(PermissionError): check_api_storage()
        with patch('pathlib.Path.cwd', return_value=Path('/app')), patch('os.geteuid', return_value=0):
            with self.assertRaises(PermissionError): check_api_storage()

    def test_write_error_is_not_swallowed(self):
        with patch('tempfile.TemporaryFile', side_effect=PermissionError('simulated')):
            with self.assertRaises(PermissionError):
                _check_upload_root(self.root, self.uid, self.gid)


if __name__ == '__main__':
    unittest.main()
