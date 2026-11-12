"""CPU-only pins for the offline 4.1.2 PRE (Xe2, native_1080) compilation.

No DLL is executed, no GPU/Wine/driver/prefix is touched. All checks are
read-only: hashes are recomputed from the pack slice and the ignored staging
directory analysis/offline-pre-412/, and the legacy auditor is only asked to
reject (fail-closed). Tests skip when the local pack, toolchain, or staging
artifacts are absent; when present, any mismatch fails instead of passing.
"""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACK = ROOT / "analysis/fsr-xmx-412/pack-40102.raw"
OCLOC = ROOT / "artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1"
STAGING = ROOT / "analysis/offline-pre-412"
INPUT = STAGING / "module-0000.cmspv"
STRIPPED = STAGING / "module-0000.spv"
ZEBIN = STAGING / "out/pre_bmg.bin"
REPRO = STAGING / "out-repro/pre_bmg.bin"
STRIPPED_BIN = STAGING / "out-stripped/pre_bmg.bin"
NATIVE_ASM = STAGING / "disasm/.text.fsr4_pre_xmx.asm"
IR_ASM = STAGING / "embedded.spvasm"
ZE_INFO = STAGING / "metadata/ze_info.yaml"

NEW_PROFILE = ROOT / "profiles/fsr4-pre-412-native1080-bmg.json"
NEW_AUDIT = ROOT / "profiles/fsr4-pre-412-native1080-payload-audit.json"

EXPECTED_ENV_SHA = (
    "ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab"
)
EXPECTED_IR_SHA = (
    "49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568"
)
EXPECTED_ZEBIN_SHA = (
    "b1781bb45a675005a81fb6679ad5f0b02d1252987a0d1f49af38cd4cf13751c2"
)
EXPECTED_CODE_SHA = (
    "68b962b5a01984d02b0bbe15bda0c8e3d04dd49ad8a58d93e5c16dbb28f8792c"
)
EXPECTED_ASM_SHA = (
    "7773a88bf497bf416d535589b0e4fb85bd3f8e14d2982a2cec52133028ba2cf9"
)
EXPECTED_IR_ASM_SHA = (
    "7ac12fd2f17cb82f7ffad5a59609366448c1bc11a7947175c0c25e19dd9d46a2"
)
EXPECTED_BUILD_OPTIONS = b"-vc-codegen  -Xfinalizer '-noDPASMacro'"
EXPECTED_ZE_INFO_SHA = (
    "5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c"
)
EXPECTED_BTIS = [8, 9, 1, 2, 3, 4, 5, 6, 7, 10, 11]
EXPECTED_ENV = {"grf_count": 128, "simd_size": 1,
                "has_dpas": True, "has_sample": True}
EXPECTED_NONZERO_PAYLOAD = [(8, 8), (16, 8), (24, 8)]

# Old build pins that the new output must differ from (IR changed) or match
# (compiler contract unchanged). Same code/zebin would be suspicious, not success.
OLD_CODE_SHA = (
    "2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f"
)
OLD_ZEBIN_SHA = (
    "3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2"
)
STRIPPED_CODE_SHA = (
    "e941cd977c6ea1b26de76a8460a07bf9c7167f0120a988438210cc3884d57e78"
)
STRIPPED_ZEBIN_SHA = (
    "ff889fb8a294588e6de85816dfe52c60a3f3bd701ed17ff82ebd39b39f7c2978"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import parse_cm_payloads
    return parse_cm_payloads


def _inspect():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import inspect_zebin
    return inspect_zebin


PACK_PRESENT = PACK.is_file()
STAGING_PRESENT = all(p.is_file() for p in (INPUT, ZEBIN, NATIVE_ASM, IR_ASM))


@unittest.skipUnless(PACK_PRESENT, "Local 4.1.2 pack-40102.raw not present")
class InputSlicePinTests(unittest.TestCase):
    def test_envelope_zero_is_the_pinned_pre(self):
        parse = _parse()
        data = PACK.read_bytes()
        recs = parse.parse(data)
        rec = recs[0]
        self.assertEqual(rec["offset"], 0)
        self.assertEqual(rec["ir_size"], 358776)
        self.assertEqual(rec["trailer_size"], 97)
        self.assertEqual(rec["envelope_size"], 358873)
        self.assertEqual(rec["end"], 358873)
        self.assertEqual(rec["ir_sha256"], EXPECTED_IR_SHA)
        self.assertEqual(rec["envelope_sha256"], EXPECTED_ENV_SHA)
        self.assertEqual(rec["embedded_string_a"],
                         "-vc-payload -Xfinalizer '-noDPASMacro'")
        self.assertEqual(rec["embedded_string_b"],
                         " -target-features=+ocl_runtime")

    def test_staged_slice_matches_pack_bytes(self):
        data = PACK.read_bytes()
        self.assertEqual(INPUT.read_bytes(), data[0:358873])
        self.assertEqual(_sha256(INPUT), EXPECTED_ENV_SHA)
        self.assertEqual(_sha256(STRIPPED), EXPECTED_IR_SHA)
        magic = INPUT.read_bytes()[:4]
        self.assertEqual(magic, b"\x03\x02\x23\x07")
        self.assertIn(b"fsr4_pre_xmx", INPUT.read_bytes()[:358776])


@unittest.skipUnless(STAGING_PRESENT, "Offline 4.1.2 staging absent")
class CompilerOutputPinTests(unittest.TestCase):
    def test_zebin_and_code_hashes(self):
        inspect = _inspect()
        report = inspect.inspect(ZEBIN.read_bytes(), "fsr4_pre_xmx")
        self.assertEqual(report["zebin_sha256"], EXPECTED_ZEBIN_SHA)
        self.assertEqual(report["code_sha256"], EXPECTED_CODE_SHA)
        self.assertEqual(report["code_size"], 30464)
        self.assertEqual(ZEBIN.stat().st_size, 395256)
        # The IR changed, so identity with the old build would be suspicious.
        self.assertNotEqual(report["zebin_sha256"], OLD_ZEBIN_SHA)
        self.assertNotEqual(report["code_sha256"], OLD_CODE_SHA)

    def test_repro_run_is_bit_identical(self):
        if not REPRO.is_file():
            self.skipTest("Repro zebin absent")
        self.assertEqual(_sha256(REPRO), EXPECTED_ZEBIN_SHA)

    def test_embedded_options_consumed_like_old_build(self):
        inspect = _inspect()
        named = inspect.sections(ZEBIN.read_bytes())
        self.assertEqual(bytes(named[".misc.buildOptions"]),
                         EXPECTED_BUILD_OPTIONS)
        self.assertEqual(bytes(named[".spv"]), STRIPPED.read_bytes())
        if not STRIPPED_BIN.is_file():
            self.skipTest("Stripped control zebin absent")
        stripped = inspect.sections(STRIPPED_BIN.read_bytes())
        self.assertEqual(bytes(stripped[".misc.buildOptions"]), b"-vc-codegen")
        srep = inspect.inspect(STRIPPED_BIN.read_bytes(), "fsr4_pre_xmx")
        self.assertEqual(srep["code_sha256"], STRIPPED_CODE_SHA)
        self.assertEqual(srep["zebin_sha256"], STRIPPED_ZEBIN_SHA)
        self.assertNotEqual(srep["code_sha256"], EXPECTED_CODE_SHA)


@unittest.skipUnless(STAGING_PRESENT, "Offline 4.1.2 staging absent")
class ZeInfoBtiPinTests(unittest.TestCase):
    def test_ze_info_bytes_unchanged(self):
        self.assertEqual(_sha256(ZE_INFO), EXPECTED_ZE_INFO_SHA)

    def test_btis_order_and_env_match_old_census(self):
        inspect = _inspect()
        report = inspect.inspect(ZEBIN.read_bytes(), "fsr4_pre_xmx")
        btis = sorted(report["binding_table_indices"],
                      key=lambda b: b["arg_index"])
        self.assertEqual([b["arg_index"] for b in btis], list(range(11)))
        self.assertEqual([b["bti_value"] for b in btis], EXPECTED_BTIS)
        for key, expected in EXPECTED_ENV.items():
            self.assertEqual(report["execution_env"][key], expected)

    def test_payload_offsets_and_sampler(self):
        inspect = _inspect()
        report = inspect.inspect(ZEBIN.read_bytes(), "fsr4_pre_xmx")
        nonzero = [(p["offset"], p["size"])
                   for p in report["payload_arguments"] if p.get("size", 0)]
        self.assertEqual(nonzero,
                         [(8, 8), (16, 8), (24, 8), (0, 8)])
        sampler = [p for p in report["payload_arguments"]
                   if p.get("addrspace") == "sampler"]
        self.assertEqual(len(sampler), 1)
        self.assertEqual(sampler[0]["arg_index"], 11)
        self.assertEqual(sampler[0].get("sampler_index"), 0)

    def test_ir_guards_and_entry(self):
        text = IR_ASM.read_text(encoding="utf-8", errors="strict")
        self.assertIn("OpEntryPoint Kernel", text)
        self.assertIn('"fsr4_pre_xmx"', text)
        self.assertIn("%uint_120 = OpConstant %uint 120", text)
        self.assertIn("%uint_540 = OpConstant %uint 540", text)


class NewProfilePinTests(unittest.TestCase):
    def test_bmg_profile_matches_staging(self):
        profile = json.loads(NEW_PROFILE.read_text())
        self.assertEqual(profile["input_sha256"], EXPECTED_ENV_SHA)
        self.assertEqual(profile["zebin_sha256"], EXPECTED_ZEBIN_SHA)
        self.assertEqual(profile["code_sha256"], EXPECTED_CODE_SHA)
        self.assertEqual(profile["kernel"], "fsr4_pre_xmx")
        self.assertEqual(profile["target_pci_id"], "0xe20b")
        self.assertEqual(profile["surface_count"], 11)
        self.assertEqual(profile["expected_push_size"], 52)
        self.assertEqual(profile["table_pc_base"], 4)
        self.assertEqual([s["bti"] for s in profile["surfaces"]],
                         EXPECTED_BTIS)
        self.assertEqual(profile["payload_review"]["evidence"],
                         "profiles/fsr4-pre-412-native1080-payload-audit.json")
        self.assertFalse(profile["payload_review"]["runtime_approved"])

    def test_audit_profile_is_blocked_not_safe(self):
        audit = json.loads(NEW_AUDIT.read_text())
        self.assertEqual(audit["status"], "static-analysis-blocked")
        self.assertEqual(audit["input_sha256"], EXPECTED_ENV_SHA)
        self.assertEqual(audit["zebin_sha256"], EXPECTED_ZEBIN_SHA)
        self.assertEqual(audit["code_sha256"], EXPECTED_CODE_SHA)
        self.assertEqual(audit["assembly_sha256"], EXPECTED_ASM_SHA)
        self.assertEqual(audit["ir_assembly_sha256"], EXPECTED_IR_ASM_SHA)
        self.assertEqual(audit["native_byte_liveness"]["status"],
                         "blocked-unsupported-opcode")
        self.assertEqual(audit["native_byte_liveness"]["possible_reads"],
                         "unknown (audit did not run to completion)")
        self.assertFalse(audit["runtime_approved"])
        self.assertEqual(
            [p["arg_index"] for p in audit["ir_surface_parameters"]],
            [0, 9, 10])
        self.assertEqual(
            [(p["offset"], p["size"]) for p in audit["nonzero_payload_fields"]],
            EXPECTED_NONZERO_PAYLOAD + [(0, 8)])


@unittest.skipUnless(STAGING_PRESENT, "Offline 4.1.2 staging absent")
class LegacyAuditorFailClosedTests(unittest.TestCase):
    def test_build_report_rejects_new_identities(self):
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from audit_pre_payload import build_report
        with self.assertRaises(ValueError):
            build_report(INPUT.read_bytes(), ZEBIN.read_bytes(),
                         NATIVE_ASM.read_bytes(), IR_ASM.read_bytes())

    def test_new_opcode_rejected_without_silent_pass(self):
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from audit_pre_payload import parse_isa
        with self.assertRaisesRegex(ValueError, "macl"):
            parse_isa(NATIVE_ASM.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
