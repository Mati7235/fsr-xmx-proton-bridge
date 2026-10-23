import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import lab_preflight


class LabPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mesa = self.root / "mesa-build"
        self.probe = self.root / "probe"
        self.mesa.mkdir()
        self.probe.mkdir()
        for relative in lab_preflight.MESA_FILES:
            path = self.mesa / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".json"):
                value = {"name": "mesa", "version": "26.1.2"} if "projectinfo" in relative else []
                path.write_text(json.dumps(value))
            else:
                path.write_bytes(b"synthetic Mesa output")
        for relative in lab_preflight.PROBE_FILES:
            path = self.probe / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"dpas.synthetic" if relative.endswith(".asm") else b"synthetic CPU fixture")
        spec = {
            "kind": lab_preflight.PROBE_KIND,
            "schema_version": 1,
            "gpu_validated": False,
            "target_vendor_id": "0x8086",
            "target_device_id": "0xe20b",
            "resource_heap_slots": [7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10],
            "untouched_heap_slots": [11, 12, 13, 14, 15],
            "surfaces": 11,
            "words_per_surface": 128,
            "cm_local_size": [1, 1, 1],
            "hardware_local_size": [32, 1, 1],
            "expected_right_mask": "0xffffffff",
            "push_size": 52,
            "table_pc_base": 4,
            "code_sha256": "a" * 64,
            "cmk_magic": "CMK3",
            "heap_set": 0,
            "heap_binding": 0,
            "payload_audit": "restricted-static-no-read",
            "runtime_approved": False,
        }
        (self.probe / "probe-spec.json").write_text(json.dumps(spec))
        (self.probe / "payload-audit.json").write_text(json.dumps({
            "status": "restricted-static-no-read", "code_sha256": "a" * 64,
            "zebin_sha256": lab_preflight.sha256(self.probe / "probe_bmg.bin"),
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_synthetic_inventory_is_not_runtime_success(self):
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertEqual(manifest["preflight"]["status"], "inventory-complete-review-required")
        self.assertEqual(manifest["preflight"]["blockers"], [])
        self.assertFalse(manifest["preflight"]["gpu_executed"])
        self.assertFalse(manifest["preflight"]["binary_semantics_verified"])
        self.assertFalse(manifest["preflight"]["runtime_ready"])
        self.assertFalse(manifest["probe"]["is_fsr_kernel"])
        self.assertFalse(manifest["fsr"]["bridge_ready"])
        library = next(item for item in manifest["mesa"]["files"] if item["path"].endswith(".so"))
        self.assertEqual(len(library["sha256"]), 64)

    def test_missing_build_artifact_fails_closed(self):
        (self.probe / "wg1_1_5.cmk").unlink()
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertEqual(manifest["preflight"]["status"], "blocked")
        self.assertTrue(any("wg1_1_5.cmk" in item for item in manifest["preflight"]["blockers"]))

    def test_non_fsr_probe_cannot_be_relabelled_as_full_fsr(self):
        spec_path = self.probe / "probe-spec.json"
        spec = json.loads(spec_path.read_text())
        spec["kind"] = "fsr-complete"
        spec_path.write_text(json.dumps(spec))
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertEqual(manifest["preflight"]["status"], "blocked")
        self.assertFalse(manifest["fsr"]["complete_kernel_present"])

    def test_wrong_target_ids_are_rejected(self):
        spec_path = self.probe / "probe-spec.json"
        spec = json.loads(spec_path.read_text())
        spec["target_vendor_id"] = "0x1234"
        spec["target_device_id"] = "0xffff"
        spec_path.write_text(json.dumps(spec))
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        blockers = "\n".join(manifest["preflight"]["blockers"])
        self.assertIn("target_vendor_id", blockers)
        self.assertIn("target_device_id", blockers)

    def test_wrong_heap_slot_maps_are_rejected(self):
        spec_path = self.probe / "probe-spec.json"
        spec = json.loads(spec_path.read_text())
        spec["resource_heap_slots"] = list(range(11))
        spec["untouched_heap_slots"] = [11, 12, 13, 14]
        spec_path.write_text(json.dumps(spec))
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        blockers = "\n".join(manifest["preflight"]["blockers"])
        self.assertIn("resource_heap_slots", blockers)
        self.assertIn("untouched_heap_slots", blockers)

    def test_non_hex_sha256_is_rejected(self):
        spec_path = self.probe / "probe-spec.json"
        spec = json.loads(spec_path.read_text())
        spec["code_sha256"] = "g" * 64
        spec_path.write_text(json.dumps(spec))
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertTrue(any("code_sha256" in item for item in manifest["preflight"]["blockers"]))

    def test_missing_dpas_evidence_blocks_inventory(self):
        (self.probe / "disasm/.text.bridge_probe.asm").write_text("mov (1) r1, r2")
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertTrue(any("DPAS" in item for item in manifest["preflight"]["blockers"]))

    def test_legacy_auto_heap_probe_is_rejected(self):
        path = self.probe / "probe-spec.json"
        spec = json.loads(path.read_text())
        spec["heap_set"] = 0xffffffff
        path.write_text(json.dumps(spec))
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertTrue(any("heap_set" in item for item in manifest["preflight"]["blockers"]))

    def test_payload_audit_must_match_inventoried_zebin(self):
        (self.probe / "probe_bmg.bin").write_bytes(b"different zebin")
        manifest = lab_preflight.make_manifest(self.mesa, self.probe)
        self.assertTrue(any("zebin_sha256" in item for item in manifest["preflight"]["blockers"]))

    def test_manifest_is_written_even_when_blocked(self):
        (self.probe / "wg1_1_5.cmk").unlink()
        output = self.root / "out/manifest.json"
        code = lab_preflight.main([
            "--mesa-build", str(self.mesa), "--probe-dir", str(self.probe),
            "--out", str(output),
        ])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.read_text())["preflight"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
