import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prepare_trace_capture as ptc


def write_icd(directory, api_version="1.4.348", library_bytes=b"CPU fixture, not a real driver"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / "libvulkan_intel.so"
    library.write_bytes(library_bytes)
    manifest = directory / "intel-local-icd.json"
    manifest.write_text(json.dumps({"file_format_version": "1.0.1",
                                    "ICD": {"api_version": api_version,
                                            "library_path": str(library)}}))
    return manifest


class TraceScaffoldTests(unittest.TestCase):
    def test_prepare_pins_static_hashes_and_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trace-pre-cpu-fixture"
            result = ptc.prepare(output)
            self.assertEqual(result, output)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["kind"], "pre-caller-trace-scaffold")
            self.assertEqual(manifest["status"], "prepared-trace-ready-not-executed")
            self.assertFalse(manifest["runtime_approved"])
            self.assertFalse(manifest["gpu_executed"])
            self.assertFalse(manifest["wine_initialized"])
            self.assertEqual(manifest["slot_map"], ptc.SLOT_MAP)
            self.assertEqual(len(manifest["slot_map"]), 11)
            self.assertEqual(manifest["expected_dispatch"]["native_1080_grid"], [120, 540, 1])
            self.assertEqual(manifest["run_policy"]["explicit_flag_required"], "--run-trace")
            self.assertTrue(manifest["run_policy"]["launcher_spawns_no_child_process"])
            for label, expected in (("dll", ptc.DLL_SHA256), ("disassembly", ptc.DISASSEMBLY_SHA256),
                                    ("pre_input_envelope", ptc.PRE_INPUT_SHA256),
                                    ("pre_zebin", ptc.PRE_ZEBIN_SHA256),
                                    ("pre_ze_info", ptc.ZE_INFO_SHA256),
                                    ("pre_iga_disasm", ptc.IGA_DISASM_SHA256),
                                    ("pre_ir_spvasm", ptc.IR_SPVASM_SHA256)):
                self.assertEqual(manifest["files"][label]["sha256"], expected, label)
            # Preparation scaffolds nothing to run and initializes no prefix.
            self.assertFalse((output / "runs").exists())
            self.assertFalse((output / "wineprefix-reserved-not-initialized").exists())
            launcher = output / "run-manual.py"
            self.assertTrue(os.access(launcher, os.X_OK))

    def test_launcher_refuses_without_explicit_flag_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = ptc.prepare(Path(directory) / "trace-pre-refusal")
            with self.assertRaisesRegex(ValueError, "--run-trace"):
                ptc.launch(output / "manifest.json")
            self.assertFalse((output / "runs").exists())
            self.assertEqual(ptc.launch_cli(str(output / "manifest.json"), []), 2)
            self.assertFalse((output / "runs").exists())

    def test_hash_change_fails_closed_before_any_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = ptc.prepare(Path(directory) / "trace-pre-tamper")
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            decoy = Path(directory) / "decoy.bin"
            decoy.write_bytes(b"tampered bytes")
            manifest["files"]["pre_zebin"]["path"] = str(decoy)
            manifest_path.write_text(json.dumps(manifest))
            with tempfile.TemporaryDirectory() as icd_dir:
                icd = write_icd(icd_dir)
                with self.assertRaisesRegex(ValueError, "SHA-256 changed"):
                    ptc.launch(manifest_path, run_trace=True, icd_manifest=icd)
            self.assertFalse((output / "runs").exists())

    def test_launch_requires_explicit_local_icd_when_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            output = ptc.prepare(Path(directory) / "trace-pre-icd")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["icd"]["status"], "pending-explicit-local-icd")
            with self.assertRaisesRegex(ValueError, "[Ii][Cc][Dd]"):
                ptc.launch(output / "manifest.json", run_trace=True,
                            run_id="no-icd-yet")
            self.assertFalse((output / "runs").exists())

    def test_explicit_launch_scaffolds_fresh_run_with_minimal_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = ptc.prepare(root / "trace-pre-run")
            icd = write_icd(root / "icd")
            run_dir, env = ptc.launch(output / "manifest.json", run_trace=True,
                                      icd_manifest=icd, run_id="cpu-only-run")
            prefix = run_dir / "wineprefix-reserved-not-initialized"
            self.assertTrue(prefix.is_dir())
            # Reserved only: empty, never initialized by the launcher.
            self.assertEqual(list(prefix.iterdir()), [])
            for name in ("user.reg", "system.reg", "userdef.reg", "drive_c"):
                self.assertFalse((prefix / name).exists())
                self.assertFalse((run_dir / name).exists())
            for name in ("home", "cache", "config", "data", "state", "tmp",
                         "evidence", "evidence/versions"):
                self.assertTrue((run_dir / name).is_dir(), name)
            self.assertEqual(env["HOME"], str(run_dir / "home"))
            self.assertEqual(env["TMPDIR"], str(run_dir / "tmp"))
            self.assertEqual(env["WINEPREFIX"], str(prefix))
            self.assertEqual(env["VK_DRIVER_FILES"], str(icd.resolve()))
            self.assertEqual(env["VK_ICD_FILENAMES"], str(icd.resolve()))
            self.assertEqual(env["PATH"], "/usr/bin:/bin")
            for forbidden in ("LD_PRELOAD", "VK_INSTANCE_LAYERS", "VK_LAYER_PATH",
                              "DRIRC_CONFIG", "STEAM_COMPAT_DATA_PATH"):
                self.assertNotIn(forbidden, env)
            evidence = run_dir / "evidence"
            self.assertTrue((evidence / "env.json").is_file())
            self.assertTrue((evidence / "pinned-hashes.json").is_file())
            self.assertTrue((evidence / "icd-manifest.json").is_file())
            planned = (evidence / "planned-command.txt").read_text()
            self.assertIn("pre-trace-capture-spec.md", planned)
            self.assertIn("pre-trace-version-checklist.md", planned)
            self.assertIn("never initializes Wine", planned)
            self.assertIn("never spawns", planned)
            stored_env = json.loads((evidence / "env.json").read_text())
            self.assertEqual(stored_env, env)

    def test_each_run_requires_a_new_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = ptc.prepare(root / "trace-pre-unique")
            icd = write_icd(root / "icd")
            ptc.launch(output / "manifest.json", run_trace=True,
                        icd_manifest=icd, run_id="unique")
            with self.assertRaises(FileExistsError):
                ptc.launch(output / "manifest.json", run_trace=True,
                            icd_manifest=icd, run_id="unique")

    def test_icd_validation_rejects_nonlocal_or_malformed_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = write_icd(root / "good")
            ptc.validate_icd_manifest(good)
            bad_version = write_icd(root / "badver", api_version="not-a-version")
            with self.assertRaisesRegex(ValueError, "[Aa][Pp][Ii]"):
                ptc.validate_icd_manifest(bad_version)
            missing_lib = root / "nolib.json"
            missing_lib.write_text(json.dumps({"file_format_version": "1.0.1",
                                               "ICD": {"api_version": "1.4.348",
                                                       "library_path": str(root / "absent.so")}}))
            with self.assertRaisesRegex(ValueError, "regular"):
                ptc.validate_icd_manifest(missing_lib)
            link_dir = root / "link"
            link_dir.mkdir()
            target = link_dir / "real.json"
            target.write_text(good.read_text())
            link = link_dir / "link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                ptc.validate_icd_manifest(link)

    def test_run_directories_are_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = ptc.prepare(root / "trace-pre-perms")
            icd = write_icd(root / "icd")
            run_dir, _ = ptc.launch(output / "manifest.json", run_trace=True,
                                    icd_manifest=icd, run_id="perms")
            mode = stat.S_IMODE(run_dir.stat().st_mode)
            self.assertEqual(mode, 0o700)


if __name__ == "__main__":
    unittest.main()
