import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import prepare_image_test
from image_probe_reference import contract
from prepare_lab_test import launch, verify_manifest


class PrepareImageTestTests(unittest.TestCase):
    def test_probe_contract_audit_and_complete_packet_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory)
            for name in prepare_image_test.PROBE_FILES:
                path = probe / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'CPU fixture')
            spec = contract()
            audit = {'status': 'synthetic-audit-test-fixture'}
            (probe / 'probe-spec.json').write_text(json.dumps(spec))
            (probe / 'payload-audit.json').write_text(json.dumps(audit))
            module = SimpleNamespace(audit_image_payload=mock.Mock(return_value=audit),
                                     pack_image_probe=mock.Mock(return_value=(b'CPU fixture', {})))
            with mock.patch.dict(sys.modules, {'build_image_probe': module}):
                self.assertEqual(prepare_image_test.validate_probe(probe), (spec, audit))
                (probe / 'wg2_1_5.cmk').write_bytes(b'changed packet')
                with self.assertRaisesRegex(ValueError, 'complete audited packet'):
                    prepare_image_test.validate_probe(probe)
                spec['expected'][0] = 999.
                (probe / 'probe-spec.json').write_text(json.dumps(spec))
                with self.assertRaisesRegex(ValueError, 'contract mismatch: expected'):
                    prepare_image_test.validate_probe(probe)

    def test_prepare_only_writes_files_and_manual_launch_remains_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mesa, probe = root / 'mesa', root / 'probe'
            probe.mkdir()
            library = mesa / prepare_image_test.ICD_RELATIVE
            library.parent.mkdir(parents=True)
            library.write_bytes(b'CPU fixture, not a real driver')
            template = mesa / prepare_image_test.ICD_TEMPLATE
            template.write_text(json.dumps({'file_format_version': '1.0.1',
                                           'ICD': {'api_version': '1.4.348'}}))
            executable = root / 'harness'
            executable.write_bytes(b'CPU fixture, must never execute')
            for name in prepare_image_test.PROBE_FILES:
                path = probe / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'CPU fixture')
            output = root / 'prepared'
            with mock.patch('prepare_image_test.validate_probe',
                            return_value=(contract(), {'status': 'CPU fixture'})):
                self.assertEqual(prepare_image_test.prepare(mesa, probe, executable, output), output)
            manifest = json.loads((output / 'manifest.json').read_text())
            verify_manifest(manifest)
            runner = mock.Mock()
            with self.assertRaisesRegex(ValueError, '--run-gpu'):
                launch(output / 'manifest.json', run_subprocess=runner)
            runner.assert_not_called()
            self.assertFalse((output / 'runs').exists())
            self.assertEqual(json.loads((output / 'intel-local-icd.json').read_text())['ICD']['library_path'],
                             str(library.resolve()))

    def test_missing_harness_blocks_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                prepare_image_test.prepare(root, root, root / 'missing', root / 'out')
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
