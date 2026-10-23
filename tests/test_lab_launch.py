import hashlib
import json
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prepare_lab_test


class LabLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lab = self.root / "lab-test"
        self.lab.mkdir()
        self.source = self.root / "inputs"
        self.source.mkdir()
        self.harness = self.source / "bridge_probe"
        self.harness.write_bytes(b"not executed by this test")
        self.library = self.source / "libvulkan_intel.so"
        self.library.write_bytes(b"local Mesa fixture")
        self.probe = self.source / "probe"
        self.probe.mkdir()
        (self.probe / "probe.spv").write_bytes(b"probe")
        (self.lab / "icd.json").write_text(json.dumps({
            "file_format_version": "1.0.1",
            "ICD": {"api_version": "1.4.348", "library_path": str(self.library)},
        }))
        self.files = {}
        for key, path in (("harness", self.harness), ("mesa_icd_library", self.library),
                          ("probe/probe.spv", self.probe / "probe.spv"),
                          ("icd_manifest", self.lab / "icd.json")):
            self.files[key] = {"path": str(path), "sha256": self.hash(path)}
        self.manifest_path = self.lab / "manifest.json"
        self.manifest_path.write_text(json.dumps({
            "status": "prepared-manual-opt-in-not-gpu-validated",
            "roots": {"mesa_build": str(self.source), "probe": str(self.probe)},
            "icd": {"manifest": str(self.lab / "icd.json"), "library_path": str(self.library)},
            "files": self.files,
        }))

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_requires_explicit_run_gpu_before_any_process_invocation(self):
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "--run-gpu"):
            prepare_lab_test.launch(self.manifest_path, run_subprocess=runner)
        runner.assert_not_called()

    def test_hash_change_fails_closed_before_run_directory_or_process(self):
        runner = Mock()
        self.harness.write_bytes(b"changed harness")
        with self.assertRaisesRegex(ValueError, "SHA-256 changed"):
            prepare_lab_test.launch(self.manifest_path, run_gpu=True, run_subprocess=runner)
        runner.assert_not_called()
        self.assertFalse((self.lab / "runs").exists())

    def test_explicit_launch_uses_new_private_run_and_minimal_environment(self):
        runner = Mock(return_value=Mock(returncode=17))
        result, run_dir = prepare_lab_test.launch(
            self.manifest_path, run_gpu=True, run_id="cpu-test-only", run_subprocess=runner)

        self.assertEqual(result.returncode, 17)
        self.assertTrue((run_dir / "wineprefix-reserved-not-initialized").is_dir())
        self.assertFalse((run_dir / "wineprefix-reserved-not-initialized" / "user.reg").exists())
        args, kwargs = runner.call_args
        self.assertEqual(args[0], [str(self.harness), "--run-gpu", "--probe-dir", str(self.probe),
                                  "--log-dir", str(run_dir / "evidence"), "--icd-manifest",
                                  str(self.lab / "icd.json"), "--icd-root", str(self.source)])
        env = kwargs["env"]
        self.assertEqual(env["HOME"], str(run_dir / "home"))
        self.assertEqual(env["WINEPREFIX"], str(run_dir / "wineprefix-reserved-not-initialized"))
        self.assertEqual(env["VK_DRIVER_FILES"], str(self.lab / "icd.json"))
        self.assertEqual(env["VK_ICD_FILENAMES"], str(self.lab / "icd.json"))
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("VK_INSTANCE_LAYERS", env)
        self.assertNotIn("VK_LAYER_PATH", env)
        self.assertNotIn("DRIRC_CONFIG", env)

    def test_each_run_requires_a_new_directory(self):
        runner = Mock(return_value=Mock(returncode=0))
        prepare_lab_test.launch(self.manifest_path, run_gpu=True, run_id="unique", run_subprocess=runner)
        with self.assertRaises(FileExistsError):
            prepare_lab_test.launch(self.manifest_path, run_gpu=True, run_id="unique", run_subprocess=runner)
        self.assertEqual(runner.call_count, 1)

    def test_cmk_requires_real_explicit_heap_header(self):
        code = b"synthetic code"
        packet = bytearray(480)
        packet[:4] = b"CMK3"
        struct.pack_into("<I", packet, 4, len(code))
        struct.pack_into("<III", packet, 168, 0, 0, 4)
        struct.pack_into("<II", packet, 472, 1, 52)
        path = self.probe / "fixture.cmk"
        spec = {"push_size": 52, "code_sha256": self.hash_bytes(code)}
        path.write_bytes(packet + code)
        prepare_lab_test.validate_cmk3(path, spec)
        struct.pack_into("<I", packet, 168, 0xffffffff)
        path.write_bytes(packet + code)
        with self.assertRaisesRegex(ValueError, "explicit heap"):
            prepare_lab_test.validate_cmk3(path, spec)

    @staticmethod
    def hash_bytes(data):
        return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
