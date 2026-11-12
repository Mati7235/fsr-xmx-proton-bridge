"""CPU-only pin tests for the XMX 4.1.2 staging file (profiles/xmx412-pins.json).

No DLL is executed, no GPU/Wine/prefix is touched. Hash recomputation over
files on disk is read-only. REQUIRED-TBD markers are asserted present and
fail-closed: anything still unknown must NOT look like a valid registry pin.
"""
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from pre_profile_registry import find_profile, load

PINS = ROOT / "profiles/xmx412-pins.json"
ANALYSIS_MANIFEST = ROOT / "analysis/fsr-xmx-412/manifest.json"
ANALYSIS_DIR = ROOT / "analysis/fsr-xmx-412"
RESDIR = Path("/tmp/opencode/xmx-new/res412")

TBD = "REQUIRED-TBD"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xmx = load_tool("decompress_xmx412")


class PinFileStructureTests(unittest.TestCase):
    def test_pins_file_is_staging_not_registry(self):
        pins = json.loads(PINS.read_text())
        self.assertEqual(pins["status"], "staging-only-not-for-registry")
        self.assertNotEqual(PINS.name, "registry.json")

    def test_source_dll_pin_is_wellformed(self):
        pins = json.loads(PINS.read_text())
        self.assertRegex(pins["source_dll_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(pins["source_dll_sha256"],
                         "fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732")

    def test_six_packs_cover_40101_40106(self):
        pins = json.loads(PINS.read_text())
        self.assertEqual(sorted(p["resource_id"] for p in pins["packs"]),
                         [40101, 40102, 40103, 40104, 40105, 40106])

    def test_pack_pins_are_wellformed(self):
        pins = json.loads(PINS.read_text())
        buckets = set()
        for pack in pins["packs"]:
            self.assertEqual(pack["index"], pack["resource_id"] - 40101)
            self.assertTrue(pack["bucket"] and pack["bucket"] not in buckets)
            buckets.add(pack["bucket"])
            self.assertGreater(pack["res_size"], 0)
            self.assertGreater(pack["loader_expected_size"], 0)
            self.assertRegex(pack["res_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(pack["raw_sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(pack["cm_envelopes"], 0)

    def test_envelope_total_is_1977(self):
        pins = json.loads(PINS.read_text())
        self.assertEqual(sum(p["cm_envelopes"] for p in pins["packs"]),
                         252 + 252 + 378 + 716 + 312 + 67)

    def test_loader_hex_sizes_match_decimals(self):
        pins = json.loads(PINS.read_text())
        for pack in pins["packs"]:
            self.assertEqual(int(pack["loader_expected_size_hex"], 16),
                             pack["loader_expected_size"])

    def test_non_pack_resources_pinned(self):
        pins = json.loads(PINS.read_text())
        by_id = {(r["type"], r["id"]): r for r in pins["non_pack_resources"]}
        self.assertEqual(set(by_id), {(16, 1), (24, 2)})
        for resource in by_id.values():
            self.assertGreater(resource["size"], 0)
            self.assertRegex(resource["sha256"], r"^[0-9a-f]{64}$")


class LoaderDigestTests(unittest.TestCase):
    def test_pins_match_commit_7059945_expected_table(self):
        pins = json.loads(PINS.read_text())
        self.assertEqual(sorted(xmx.EXPECTED), [40101, 40102, 40103, 40104, 40105, 40106])
        for pack in pins["packs"]:
            meta = xmx.EXPECTED[pack["resource_id"]]
            self.assertEqual(meta["index"], pack["index"])
            self.assertEqual(meta["bucket"], pack["bucket"])
            self.assertEqual(meta["res_size"], pack["res_size"])
            self.assertEqual(meta["res_sha256"], pack["res_sha256"])
            self.assertEqual(meta["raw_size"], pack["loader_expected_size"])
            self.assertEqual(meta["raw_sha256"], pack["raw_sha256"])
            self.assertEqual(meta["cm_envelopes"], pack["cm_envelopes"])


@unittest.skipUnless(ANALYSIS_MANIFEST.is_file(), "Local 4.1.2 analysis manifest absent")
class AnalysisManifestTests(unittest.TestCase):
    def test_pins_match_analysis_manifest(self):
        pins = json.loads(PINS.read_text())
        manifest = json.loads(ANALYSIS_MANIFEST.read_text())
        self.assertEqual(manifest["origin"]["sha256"], pins["source_dll_sha256"])
        by_id = {p["resource_id"]: p for p in manifest["packs"]}
        for pack in pins["packs"]:
            entry = by_id[pack["resource_id"]]
            self.assertEqual(entry["res_size"], pack["res_size"])
            self.assertEqual(entry["res_sha256"], pack["res_sha256"])
            self.assertEqual(entry["raw_size"], pack["loader_expected_size"])
            self.assertEqual(entry["raw_sha256"], pack["raw_sha256"])
            self.assertEqual(entry["cm_envelopes"], pack["cm_envelopes"])


@unittest.skipUnless(RESDIR.is_dir(), "Optional local 4.1.2 resource dir absent")
class ResourceDirTests(unittest.TestCase):
    def test_resource_files_match_pins(self):
        pins = json.loads(PINS.read_text())
        manifest = json.loads((RESDIR / "manifest.json").read_bytes())
        blobs = {e["path"][1]: e for e in manifest["resources"] if e["path"][0] == 10}
        non_packs = {(e["path"][0], e["path"][1]): e for e in manifest["resources"]
                     if e["path"][0] in (16, 24)}
        for pack in pins["packs"]:
            entry = blobs[pack["resource_id"]]
            blob = (RESDIR / entry["file"]).read_bytes()
            self.assertEqual(len(blob), pack["res_size"])
            self.assertEqual(hashlib.sha256(blob).hexdigest(), pack["res_sha256"])
        for resource in pins["non_pack_resources"]:
            entry = non_packs[(resource["type"], resource["id"])]
            blob = (RESDIR / entry["file"]).read_bytes()
            self.assertEqual(len(blob), resource["size"])
            self.assertEqual(hashlib.sha256(blob).hexdigest(), resource["sha256"])


@unittest.skipUnless((ANALYSIS_DIR / "pack-40102.raw").is_file(),
                     "Local 4.1.2 Xe2 pack raw absent")
class Xe2PackDigestTests(unittest.TestCase):
    def test_xe2_decompressed_digest_matches_pin(self):
        pins = json.loads(PINS.read_text())
        pack = next(p for p in pins["packs"] if p["resource_id"] == 40102)
        raw = (ANALYSIS_DIR / "pack-40102.raw").read_bytes()
        self.assertEqual(len(raw), pack["loader_expected_size"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), pack["raw_sha256"])


class TbdFailClosedTests(unittest.TestCase):
    def test_disassembly_is_tbd(self):
        pins = json.loads(PINS.read_text())
        self.assertEqual(pins["disassembly_412"], TBD)

    def test_pre_kernel_hashes_are_tbd(self):
        pins = json.loads(PINS.read_text())
        pre = pins["pre_xe2_412"]
        for key in ("code_sha256", "input_sha256", "zebin_sha256"):
            self.assertEqual(pre[key], TBD, f"{key} must stay REQUIRED-TBD, never invented")

    def test_pre_layout_fields_are_tbd(self):
        pins = json.loads(PINS.read_text())
        pre = pins["pre_xe2_412"]
        for key in ("variant", "table_pc_base", "expected_push_size",
                    "surface_count", "profile"):
            self.assertEqual(pre[key], TBD, f"{key} must stay REQUIRED-TBD")

    def test_tbd_is_not_a_valid_registry_digest(self):
        self.assertIsNone(HEX64.match(TBD))
        self.assertIsNone(find_profile(TBD))

    def test_fragment_would_fail_registry_load(self):
        pins = json.loads(PINS.read_text())
        fragment = dict(pins["future_registry_entry_fragment"])
        fragment.pop("_comment", None)
        with tempfile.TemporaryDirectory() as tmp:
            candidate = {
                "schema_version": 1,
                "status": "experimental-offline-only",
                "profiles": [fragment],
            }
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps(candidate))
            with self.assertRaises(ValueError):
                load(path)


class RegistryAcceptanceProbeTests(unittest.TestCase):
    def test_no_412_code_in_registry_today(self):
        pins = json.loads(PINS.read_text())
        registry = load()
        for pack in pins["packs"]:
            self.assertIsNone(find_profile(pack["raw_sha256"], registry),
                              "a decompressed-pack digest must never select a kernel profile")
        self.assertIsNone(find_profile("0" * 64, registry))
        self.assertIsNone(find_profile("f" * 64, registry))

    def test_legacy_path_keeps_global_behavior(self):
        self.assertIsNone(find_profile("0" * 64))
        self.assertIsNone(find_profile("f" * 64))


if __name__ == "__main__":
    unittest.main()
