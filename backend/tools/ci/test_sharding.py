"""Standard-library tests for the CI release coverage gate."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from shard_tests import discover, partition
from verify_shards import verify


class ShardingTests(unittest.TestCase):
    def test_partition_is_deterministic_and_covers_new_modules(self):
        files = ['test_a.py', 'test_b.py', 'new/test_new.py']
        groups = partition(files, {'test_a.py': 8, 'test_b.py': 2}, 3)
        self.assertEqual(groups, partition(list(reversed(files)), {'test_a.py': 8, 'test_b.py': 2}, 3))
        self.assertEqual(sorted(f for g in groups for f in g['files']), sorted(files))

    def test_invalid_input_rejected(self):
        for files, weights, count in [([], {}, 3), (['test_a.py'] * 2, {}, 3),
                                       (['test_a.py'], {}, 0),
                                       (['test_a.py'], {'test_a.py': float('nan')}, 3)]:
            with self.assertRaises(ValueError):
                partition(files, weights, count)

    def fixture(self, root):
        tests = root / 'tests'; evidence = root / 'evidence'
        tests.mkdir(); evidence.mkdir()
        for name in ['test_a.py', 'test_b.py', 'test_c.py']:
            (tests / name).write_text('')
        groups = partition(discover(tests), {}, 3)
        for index, group in enumerate(groups, 1):
            manifest = {'shard': index, 'count': 3, 'groups': groups,
                        'plan_sha256': hashlib.sha256(json.dumps(groups, sort_keys=True).encode()).hexdigest()}
            (evidence / f'shard-{index}-manifest.json').write_text(json.dumps(manifest))
            suite = ET.Element('testsuite')
            for name in group['files']:
                ET.SubElement(suite, 'testcase', classname='tests.' + name[:-3], name='test_example')
            ET.ElementTree(suite).write(evidence / f'backend-junit-{index}.xml')
        return tests, evidence

    def test_successful_complete_reports_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            verify(*self.fixture(Path(directory)), 3)

    def test_missing_shard_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            tests, evidence = self.fixture(Path(directory))
            (evidence / 'shard-2-manifest.json').unlink()
            with self.assertRaises(FileNotFoundError):
                verify(tests, evidence, 3)

    def test_failed_test_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            tests, evidence = self.fixture(Path(directory))
            path = evidence / 'backend-junit-1.xml'; tree = ET.parse(path)
            ET.SubElement(next(tree.iter('testcase')), 'failure').text = 'failed'
            tree.write(path)
            with self.assertRaises(ValueError):
                verify(tests, evidence, 3)

    def test_new_unassigned_file_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            tests, evidence = self.fixture(Path(directory))
            (tests / 'test_added.py').write_text('')
            with self.assertRaises(ValueError):
                verify(tests, evidence, 3)

    def test_wrong_module_report_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            tests, evidence = self.fixture(Path(directory))
            path = evidence / 'backend-junit-1.xml'; tree = ET.parse(path)
            next(tree.iter('testcase')).set('classname', 'tests.test_unrelated');tree.write(path)
            with self.assertRaises(ValueError):
                verify(tests, evidence, 3)

    def test_repeated_module_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            tests, evidence = self.fixture(Path(directory))
            path = evidence / 'shard-1-manifest.json'; manifest = json.loads(path.read_text())
            manifest['groups'][0]['files'].append(manifest['groups'][1]['files'][0])
            manifest['plan_sha256'] = hashlib.sha256(json.dumps(manifest['groups'], sort_keys=True).encode()).hexdigest()
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify(tests, evidence, 3)


if __name__ == '__main__':
    unittest.main()
