"""CPU-only pins for the local Intel offline toolchain and the new Xe2 PRE block.

No DLL is executed, no GPU/Wine/driver/prefix is touched. All checks are
read-only: deb hashes are recomputed, extracted files are checked for
existence, and pack-40102.raw is parsed with the stdlib footer parser
(tools/parse_cm_payloads). Outputs under analysis/ and artifacts/ stay
ignored by git; this test only reads them.
"""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACK = ROOT / "analysis/fsr-xmx-412/pack-40102.raw"
PACK_MANIFEST = ROOT / "analysis/fsr-xmx-412/manifest.json"
TOOLCHAIN_JSON = ROOT / "profiles/intel-toolchain.json"
OLD_PROFILE = ROOT / "profiles/fsr4-pre-native1080-bmg.json"

# Pinned from profiles/intel-toolchain.json (IGC 2.10.10+18926, ocloc 25.18.33578.6).
EXPECTED_DEBS = {
    "artifacts/original/intel-toolchain/igc-core.deb":
        "ec3b8e6bb3d6371d3b9963c32ddb1d5315e6b0c3f4ae1d91a7515b5a8907ffe6",
    "artifacts/original/intel-toolchain/igc-opencl.deb":
        "0c631f25cd8394a2f7640f9e35b593cc98ca3fbe922419c5cb20b2281477ef4c",
    "artifacts/original/intel-toolchain/ocloc.deb":
        "c772db8891539890237d50c357af1480b22cbd859c0b8afb5355f605a818d758",
}

# Extracted layout produced without installation (data.tar.gz / data.tar.zst only).
EXPECTED_EXTRACTED = [
    "artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1",
    "artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu/libocloc.so",
    "artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigc.so.2.10.10+18926",
    "artifacts/extracted/intel-toolchain/igc/usr/local/lib/libiga64.so.2.10.10+18926",
    "artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigdfcl.so.2.10.10+18926",
    "artifacts/extracted/intel-toolchain/igc/usr/local/lib/libopencl-clang2.so.15",
]

# New Xe2 pack identity (analysis/fsr-xmx-412/manifest.json, resource 40102).
EXPECTED_PACK_SIZE = 23682325
EXPECTED_PACK_SHA256 = (
    "d88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491"
)

# New PRE Xe2 4.1.2 native_1080 candidate: first CM envelope of pack-40102.raw.
# Identified by static footer parse only (no execution). All 18 PRE envelopes
# share ir_size 358776 / trailer 97 and the same embedded option strings; only
# record 0 is pinned by full hash here, the rest by structural invariants below.
EXPECTED_PRE = {
    "offset": 0,
    "ir_size": 358776,
    "trailer_size": 97,
    "envelope_size": 358873,
    "end": 358873,
    "ir_sha256": (
        "49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568"
    ),
    "envelope_sha256": (
        "ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab"
    ),
    "embedded_string_a": "-vc-payload -Xfinalizer '-noDPASMacro'",
    "embedded_string_b": " -target-features=+ocl_runtime",
}
EXPECTED_PRE_COUNT = 18
EXPECTED_PRE_IR_SIZE = 358776
EXPECTED_TOTAL_RECORDS = 252

# Old census expectations that the new compile must reproduce (order and BTIs).
# From profiles/fsr4-pre-native1080-bmg.json and analysis/offline-pre/full/ze_info.yaml.
EXPECTED_BTIS = [8, 9, 1, 2, 3, 4, 5, 6, 7, 10, 11]
EXPECTED_PUSH_SIZE = 52
EXPECTED_TABLE_PC_BASE = 4
EXPECTED_KERNEL = "fsr4_pre_xmx"
EXPECTED_ENV = {"grf_count": 128, "simd_size": 1,
                "has_dpas": True, "has_sample": True}


def _parse():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import parse_cm_payloads
    return parse_cm_payloads


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


TOOLCHAIN_PRESENT = TOOLCHAIN_JSON.exists() and all(
    (ROOT / rel).exists() for rel in list(EXPECTED_DEBS) + EXPECTED_EXTRACTED)
PACK_PRESENT = PACK.exists()


@unittest.skipUnless(TOOLCHAIN_PRESENT, "Local Intel toolchain not present")
class ToolchainIntactTests(unittest.TestCase):
    def test_deb_hashes_match_profile(self):
        pinned = {a["local_file"]: a["sha256"]
                  for a in json.loads(TOOLCHAIN_JSON.read_text())["assets"]}
        self.assertEqual(pinned, EXPECTED_DEBS)
        for rel, expected in EXPECTED_DEBS.items():
            self.assertEqual(_sha256(ROOT / rel), expected, rel)

    def test_extracted_layout_present(self):
        for rel in EXPECTED_EXTRACTED:
            self.assertTrue((ROOT / rel).is_file(), rel)


@unittest.skipUnless(PACK_PRESENT, "Local 4.1.2 pack-40102.raw not present")
class PreBlockReferenceTests(unittest.TestCase):
    def test_pack_identity(self):
        self.assertEqual(PACK.stat().st_size, EXPECTED_PACK_SIZE)
        self.assertEqual(_sha256(PACK), EXPECTED_PACK_SHA256)

    def test_native1080_envelope_pin(self):
        parse = _parse()
        data = PACK.read_bytes()
        records = parse.parse(data)
        self.assertEqual(len(records), EXPECTED_TOTAL_RECORDS)
        rec = records[0]
        for key, expected in EXPECTED_PRE.items():
            self.assertEqual(rec[key], expected, key)
        blob = data[rec["offset"]:rec["end"]]
        self.assertEqual(hashlib.sha256(blob).hexdigest(),
                         EXPECTED_PRE["envelope_sha256"])
        ir = data[rec["offset"]:rec["offset"] + rec["ir_size"]]
        self.assertEqual(hashlib.sha256(ir).hexdigest(),
                         EXPECTED_PRE["ir_sha256"])
        self.assertTrue(ir.startswith(b"\x03\x02\x23\x07"))
        self.assertIn(EXPECTED_KERNEL.encode(), ir)

    def test_pre_family_structure(self):
        parse = _parse()
        data = PACK.read_bytes()
        records = parse.parse(data)
        pres = [r for r in records if r["ir_size"] == EXPECTED_PRE_IR_SIZE]
        self.assertEqual(len(pres), EXPECTED_PRE_COUNT)
        for rec in pres:
            self.assertEqual(rec["trailer_size"], 97)
            self.assertEqual(rec["embedded_string_a"],
                             EXPECTED_PRE["embedded_string_a"])
            self.assertEqual(rec["embedded_string_b"],
                             EXPECTED_PRE["embedded_string_b"])
            ir = data[rec["offset"]:rec["offset"] + rec["ir_size"]]
            self.assertIn(b"fsr4_pre_xmx", ir)


class OldCensusExpectationTests(unittest.TestCase):
    def test_versioned_profile_pins_btis_order_push(self):
        profile = json.loads(OLD_PROFILE.read_text())
        self.assertEqual(profile["kernel"], EXPECTED_KERNEL)
        self.assertEqual(profile["expected_push_size"], EXPECTED_PUSH_SIZE)
        self.assertEqual(profile["table_pc_base"], EXPECTED_TABLE_PC_BASE)
        got = [(s["arg_index"], s["bti"]) for s in profile["surfaces"]]
        self.assertEqual([a for a, _ in got], list(range(11)))
        self.assertEqual([b for _, b in got], EXPECTED_BTIS)

    def test_expected_execution_env_documented(self):
        # Hard pins from analysis/offline-pre/full/ze_info.yaml + summary.json
        # (both ignored artifacts); kept here so the expectation survives
        # without those files and the new compile can be compared against it.
        self.assertEqual(EXPECTED_ENV["grf_count"], 128)
        self.assertEqual(EXPECTED_ENV["simd_size"], 1)
        self.assertIs(EXPECTED_ENV["has_dpas"], True)
        self.assertIs(EXPECTED_ENV["has_sample"], True)


if __name__ == "__main__":
    unittest.main()
