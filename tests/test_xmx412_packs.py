"""CPU-only verification of XMX 4.1.2 packs 40101/40102/40103.

Static analysis only: the DLL is read as bytes and never loaded, no GPU,
Wine, Steam, prefix, driver, or original-artifact state is touched. The
local libwim decoder and ``spirv-dis`` (when present) are the only native
code involved. All local-artifact cases fail closed on any size, digest,
or count mismatch and skip when the ignored local files are absent.
"""

import hashlib
import importlib.util
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xmx = load("decompress_xmx412")
payloads = load("parse_cm_payloads")
carve = load("carve_spirv")

DLL412 = ROOT / "artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll"
DLL412_SHA256 = "fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732"
RAWDIR = ROOT / "analysis/fsr-xmx-412"
LIBWIM = ROOT / "upstream/wimlib/.libs/libwim.so"
OLD_XE2_SPV = ROOT / "analysis/fsr-resources/resource-0001-first.spv"
OLD_XE2_SPVASM = ROOT / "analysis/fsr-resources/xe2-first.spvasm"

FOCUS = (40101, 40102, 40103)
FOCUS_COUNTS = {40101: 252, 40102: 252, 40103: 378}
CARVE_COUNTS = {40101: 246, 40102: 252, 40103: 378}
DXBC_COUNTS = {40101: 18, 40102: 0, 40103: 0}

# Pinned PRE Xe2 block: CM envelope index 0 of pack 40102 (offset 0).
PRE = {
    "pack": 40102,
    "cm_index": 0,
    "offset": 0,
    "ir_size": 358776,
    "trailer_size": 97,
    "envelope_size": 358873,
    "option_a": "-vc-payload -Xfinalizer '-noDPASMacro'",
    "option_b": " -target-features=+ocl_runtime",
    "ir_sha256": "49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568",
    "entry": "fsr4_pre_xmx",
    "bound": 11188,
}
OLD_PRE = {
    "ir_size": 330108,
    "ir_sha256": "1d10c34ef21007bdc11c93647ef9ea482f7988e1aee705e082c7eb1722bd44a2",
    "bound": 10274,
    "option_a": "-vc-payload -Xfinalizer '-noDPASMacro'",
    "option_b": " -target-features=+ocl_runtime",
}


def meta_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_local_inputs():
    return (
        DLL412.is_file()
        and LIBWIM.exists()
        and all((RAWDIR / f"pack-{rid}.raw").is_file() for rid in FOCUS)
    )


class PinTableTests(unittest.TestCase):
    def test_focus_counts_match_7059945(self):
        self.assertEqual(FOCUS_COUNTS, {40101: 252, 40102: 252, 40103: 378})
        for rid, count in FOCUS_COUNTS.items():
            self.assertEqual(xmx.EXPECTED[rid]["cm_envelopes"], count)

    def test_six_pack_total_is_1977(self):
        self.assertEqual(
            sum(m["cm_envelopes"] for m in xmx.EXPECTED.values()),
            252 + 252 + 378 + 716 + 312 + 67,
        )

    def test_pre_pin_is_wellformed(self):
        self.assertEqual(PRE["envelope_size"], PRE["ir_size"] + PRE["trailer_size"])
        self.assertRegex(PRE["ir_sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(PRE["ir_size"], OLD_PRE["ir_size"])


@unittest.skipUnless(has_local_inputs(), "Local 4.1.2 inputs are not present")
class ReproducibilityTests(unittest.TestCase):
    def test_dll_sha_pinned(self):
        self.assertEqual(hashlib.sha256(DLL412.read_bytes()).hexdigest(), DLL412_SHA256)

    def test_stored_raw_matches_pins(self):
        for rid in FOCUS:
            meta = xmx.EXPECTED[rid]
            data = (RAWDIR / f"pack-{rid}.raw").read_bytes()
            self.assertEqual(len(data), meta["raw_size"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), meta["raw_sha256"])

    def test_rerun_decoder_is_byte_identical(self):
        packs = xmx.packs_from_dll(DLL412.read_bytes())
        self.assertEqual(sorted(packs), [40101, 40102, 40103, 40104, 40105, 40106])
        for rid in FOCUS:
            raw = xmx.decode_and_verify(packs[rid], dict(xmx.EXPECTED[rid]), LIBWIM)
            stored = (RAWDIR / f"pack-{rid}.raw").read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), meta_hex(stored))
            self.assertEqual(len(raw), len(stored))

    def test_cm_counts(self):
        for rid in FOCUS:
            data = (RAWDIR / f"pack-{rid}.raw").read_bytes()
            self.assertEqual(len(payloads.parse(data)), FOCUS_COUNTS[rid])


@unittest.skipUnless(has_local_inputs(), "Local 4.1.2 inputs are not present")
class BlockInventoryTests(unittest.TestCase):
    def test_carve_counts_and_40101_post_gap(self):
        for rid in FOCUS:
            data = (RAWDIR / f"pack-{rid}.raw").read_bytes()
            self.assertEqual(len(carve.carve(data)), CARVE_COUNTS[rid])
        # 40101: 252 SPIR-V magics but 6 post_xmx envelopes do not satisfy the
        # heuristic carve walk; the CM footer parser stays authoritative.
        data = (RAWDIR / "pack-40101.raw").read_bytes()
        records = payloads.parse(data)
        carved_starts = {m["offset"] for m in carve.carve(data)}
        missing = [r for r in records if r["offset"] not in carved_starts]
        self.assertEqual(len(missing), 6)
        for record in missing:
            blob = data[record["offset"] : record["offset"] + record["ir_size"]]
            self.assertIn(b"fsr4_post_xmx", blob)
            self.assertEqual(record["ir_size"], 189728)

    def test_gap_profile_dxbc_and_weights(self):
        data = (RAWDIR / "pack-40101.raw").read_bytes()
        gaps = payloads.gaps(data, payloads.parse(data))
        self.assertEqual(len(gaps), 251)
        self.assertEqual(sum(len(g["dxbc_candidates"]) for g in gaps), DXBC_COUNTS[40101])
        weights = [g for g in gaps if not g["all_zero"] and not g["dxbc_candidates"]]
        self.assertEqual(len(weights), 6)
        for gap in weights:
            self.assertEqual(gap["size"], 134938)
        for rid in (40102, 40103):
            pack = (RAWDIR / f"pack-{rid}.raw").read_bytes()
            pack_gaps = payloads.gaps(pack, payloads.parse(pack))
            self.assertTrue(all(g["all_zero"] for g in pack_gaps))
            self.assertEqual(sum(len(g["dxbc_candidates"]) for g in pack_gaps), 0)
            self.assertEqual(len(pack_gaps), {40102: 251, 40103: 377}[rid])

    @unittest.skipUnless(shutil.which("spirv-dis"), "spirv-dis is not installed")
    def test_all_focus_irs_disassemble(self):
        for rid in FOCUS:
            data = (RAWDIR / f"pack-{rid}.raw").read_bytes()
            records = payloads.parse(data)
            failures = disassemble_failures(data, records)
            self.assertEqual(failures, [], f"pack {rid} spirv-dis failures: {failures[:3]}")
            self.assertEqual(len(records), FOCUS_COUNTS[rid])


def disassemble_failures(data: bytes, records: list) -> list:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.spv"
        for index, record in enumerate(records):
            probe.write_bytes(data[record["offset"] : record["offset"] + record["ir_size"]])
            done = subprocess.run(
                ["spirv-dis", str(probe)], capture_output=True, text=True
            )
            if done.returncode != 0:
                failures.append((index, done.stderr[:200]))
    return failures


@unittest.skipUnless(has_local_inputs(), "Local 4.1.2 inputs are not present")
class PreXe2Tests(unittest.TestCase):
    def test_pre_block_pinned_in_40102(self):
        data = (RAWDIR / "pack-40102.raw").read_bytes()
        records = payloads.parse(data)
        record = records[PRE["cm_index"]]
        self.assertEqual(record["offset"], PRE["offset"])
        self.assertEqual(record["ir_size"], PRE["ir_size"])
        self.assertEqual(record["trailer_size"], PRE["trailer_size"])
        self.assertEqual(record["envelope_size"], PRE["envelope_size"])
        self.assertEqual(record["embedded_string_a"], PRE["option_a"])
        self.assertEqual(record["embedded_string_b"], PRE["option_b"])
        self.assertEqual(record["ir_sha256"], PRE["ir_sha256"])
        blob = data[record["offset"] : record["offset"] + record["ir_size"]]
        self.assertIn(PRE["entry"].encode(), blob)
        magic, _version, _generator, bound, schema = struct.unpack_from("<5I", blob, 0)
        self.assertEqual((magic, bound, schema), (0x07230203, PRE["bound"], 0))
        modules = carve.carve(data)
        self.assertEqual(modules[0]["offset"], PRE["offset"])
        self.assertEqual(modules[0]["entries"][0]["name"], PRE["entry"])

    @unittest.skipUnless(
        OLD_XE2_SPV.is_file(), "Old Xe2 reference SPV is not present"
    )
    def test_pre_ir_size_and_options_vs_old(self):
        old = OLD_XE2_SPV.read_bytes()
        self.assertEqual(len(old), OLD_PRE["ir_size"])
        self.assertEqual(hashlib.sha256(old).hexdigest(), OLD_PRE["ir_sha256"])
        _magic, _ver, _gen, old_bound, _schema = struct.unpack_from("<5I", old, 0)
        self.assertEqual(old_bound, OLD_PRE["bound"])
        data = (RAWDIR / "pack-40102.raw").read_bytes()
        record = payloads.parse(data)[PRE["cm_index"]]
        self.assertEqual(record["embedded_string_a"], OLD_PRE["option_a"])
        self.assertEqual(record["embedded_string_b"], OLD_PRE["option_b"])
        self.assertGreater(record["ir_size"], OLD_PRE["ir_size"])
        self.assertEqual(record["ir_size"] - OLD_PRE["ir_size"], 28668)
        self.assertEqual(PRE["bound"] - OLD_PRE["bound"], 914)


if __name__ == "__main__":
    unittest.main()
