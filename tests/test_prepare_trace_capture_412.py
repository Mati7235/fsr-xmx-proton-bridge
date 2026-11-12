import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prepare_trace_capture_412 as ptc


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


class Scaffold412Tests(unittest.TestCase):
    def test_prepare_pins_412_hashes_and_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trace-412-cpu-fixture"
            result = ptc.prepare(output)
            self.assertEqual(result, output)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["kind"], "xmx412-pre-caller-trace-scaffold")
            self.assertEqual(manifest["status"], "prepared-trace-ready-not-executed")
            self.assertFalse(manifest["runtime_approved"])
            self.assertFalse(manifest["gpu_executed"])
            self.assertFalse(manifest["wine_initialized"])
            self.assertEqual(manifest["slot_map"], ptc.SLOT_MAP)
            self.assertEqual(len(manifest["slot_map"]), 11)
            self.assertEqual(manifest["expected_dispatch"]["native_1080_grid"], [120, 540, 1])
            self.assertEqual(manifest["expected_dispatch"]["descriptor_tables"], 11)
            self.assertEqual(manifest["run_policy"]["explicit_flags_required"],
                              ["--run-trace", "--icd-manifest"])
            self.assertTrue(manifest["run_policy"]["explicit_icd_manifest_required"])
            self.assertTrue(manifest["run_policy"]["launcher_spawns_no_child_process"])
            # 4.1.2 identity pins.
            self.assertEqual(manifest["xmx412"]["dll_sha256"], ptc.DLL_SHA256_412)
            self.assertEqual(manifest["xmx412"]["dll_sha256"],
                              "fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732")
            pre = manifest["xmx412"]["pre_native1080"]
            self.assertEqual(pre["ir_sha256"], ptc.PRE_IR_SHA256_412)
            self.assertEqual(pre["envelope_sha256"], ptc.PRE_ENVELOPE_SHA256_412)
            self.assertEqual(pre["ir_sha256"],
                              "49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568")
            self.assertEqual(pre["envelope_sha256"],
                              "ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab")
            self.assertEqual(len(manifest["xmx412"]["packs"]), 6)
            self.assertEqual(sorted(p["resource_id"] for p in manifest["xmx412"]["packs"]),
                              [40101, 40102, 40103, 40104, 40105, 40106])
            for label, expected in (("dll_412", ptc.DLL_SHA256_412),
                                    ("pre_envelope_cmspv", ptc.PRE_ENVELOPE_SHA256_412),
                                    ("d3d12_header", ptc.D3D12_HEADER_SHA256),
                                    ("dxgi_format_header", ptc.DXGI_FORMAT_HEADER_SHA256)):
                self.assertEqual(manifest["files"][label]["sha256"], expected, label)
            for resource_id, _, _, raw_sha, _, _, _, _ in ptc.PACKS_412:
                self.assertEqual(manifest["files"][f"pack_{resource_id}"]["sha256"],
                                  raw_sha, f"pack_{resource_id}")
            self.assertIn("pins_412", manifest["files"])
            self.assertIn("runbook/docs/spiderman-trace-runbook.md", manifest["files"])
            # Preparation scaffolds nothing to run and initializes no prefix.
            self.assertFalse((output / "runs").exists())
            self.assertFalse((output / "wineprefix-reserved-not-initialized").exists())
            launcher = output / "run-manual.py"
            self.assertTrue(os.access(launcher, os.X_OK))

    def test_launcher_refuses_without_both_explicit_flags_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = ptc.prepare(Path(directory) / "trace-412-refusal")
            with self.assertRaisesRegex(ValueError, "--run-trace"):
                ptc.launch(output / "manifest.json")
            self.assertFalse((output / "runs").exists())
            with tempfile.TemporaryDirectory() as icd_dir:
                icd = write_icd(icd_dir)
                with self.assertRaisesRegex(ValueError, "--run-trace"):
                    ptc.launch(output / "manifest.json", run_trace=False,
                                icd_manifest=icd)
                with self.assertRaisesRegex(ValueError, "--icd-manifest"):
                    ptc.launch(output / "manifest.json", run_trace=True,
                                icd_manifest=None)
            self.assertEqual(ptc.launch_cli(str(output / "manifest.json"), []), 2)
            self.assertFalse((output / "runs").exists())

    def test_hash_change_fails_closed_before_any_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = ptc.prepare(Path(directory) / "trace-412-tamper")
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            decoy = Path(directory) / "decoy.bin"
            decoy.write_bytes(b"tampered bytes")
            manifest["files"]["pack_40102"]["path"] = str(decoy)
            manifest_path.write_text(json.dumps(manifest))
            with tempfile.TemporaryDirectory() as icd_dir:
                icd = write_icd(icd_dir)
                with self.assertRaisesRegex(ValueError, "SHA-256 changed"):
                    ptc.launch(manifest_path, run_trace=True, icd_manifest=icd)
            self.assertFalse((output / "runs").exists())

    def test_launch_requires_explicit_icd_even_when_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            output = ptc.prepare(Path(directory) / "trace-412-icd")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["icd"]["status"], "pending-explicit-local-icd")
            with self.assertRaisesRegex(ValueError, "[Ii][Cc][Dd]"):
                ptc.launch(output / "manifest.json", run_trace=True,
                            run_id="no-icd-yet")
            self.assertFalse((output / "runs").exists())

    def test_pinned_icd_must_match_at_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = write_icd(root / "icd-a")
            output = ptc.prepare(root / "trace-412-pinned", icd_manifest=first)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["icd"]["status"], "pinned-explicit-local-icd")
            other = write_icd(root / "icd-b", library_bytes=b"a different fixture driver")
            with self.assertRaisesRegex(ValueError, "[Ii][Cc][Dd]"):
                ptc.launch(output / "manifest.json", run_trace=True,
                            icd_manifest=other, run_id="mismatch")
            self.assertFalse((output / "runs").exists())
            run_dir, _ = ptc.launch(output / "manifest.json", run_trace=True,
                                    icd_manifest=first, run_id="match")
            self.assertTrue(run_dir.is_dir())

    def test_explicit_launch_scaffolds_fresh_run_with_minimal_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = ptc.prepare(root / "trace-412-run")
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
            self.assertEqual(env["VKD3D_DEBUG"], "trace")
            self.assertEqual(env["PATH"], "/usr/bin:/bin")
            for forbidden in ("LD_PRELOAD", "VK_INSTANCE_LAYERS", "VK_LAYER_PATH",
                              "DRIRC_CONFIG", "STEAM_COMPAT_DATA_PATH"):
                self.assertNotIn(forbidden, env)
            evidence = run_dir / "evidence"
            self.assertTrue((evidence / "env.json").is_file())
            self.assertTrue((evidence / "pinned-hashes.json").is_file())
            self.assertTrue((evidence / "icd-manifest.json").is_file())
            planned = (evidence / "planned-command.txt").read_text()
            self.assertIn("spiderman-trace-runbook.md", planned)
            self.assertIn("pre-trace-capture-spec.md", planned)
            self.assertIn("pre-trace-version-checklist.md", planned)
            self.assertIn("VKD3D_DEBUG", planned)
            self.assertIn("never initializes Wine", planned)
            self.assertIn("never spawns", planned)
            stored_env = json.loads((evidence / "env.json").read_text())
            self.assertEqual(stored_env, env)

    def test_each_run_requires_a_new_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = ptc.prepare(root / "trace-412-unique")
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
            output = ptc.prepare(root / "trace-412-perms")
            icd = write_icd(root / "icd")
            run_dir, _ = ptc.launch(output / "manifest.json", run_trace=True,
                                    icd_manifest=icd, run_id="perms")
            mode = stat.S_IMODE(run_dir.stat().st_mode)
            self.assertEqual(mode, 0o700)


if __name__ == "__main__":
    unittest.main()
