"""CPU-only tests for the offline profile-per-hash selector and cache identity.

No GPU, no Wine, no installs. The CMK3 reader block is validated with
synthetic layouts compiled as host C; the XeSS-global legacy path must stay
byte-identical in behavior.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from pre_profile_registry import find_profile, load, registry_gen

REGISTRY = ROOT / "profiles/registry.json"
PATCH = ROOT / "patches/0001-anv-cmk3-explicit-mapping.patch"
PROFILE = ROOT / "profiles/fsr4-pre-native1080-bmg.json"
KNOWN_CODE = "2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f"


class RegistryTests(unittest.TestCase):
    def test_registry_loads_and_selects_reviewed_pre(self) -> None:
        registry = load()
        self.assertEqual(registry["status"], "experimental-offline-only")
        entry = find_profile(KNOWN_CODE, registry)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["kernel"], "fsr4_pre_xmx")
        self.assertEqual((entry["table_pc_base"], entry["expected_push_size"]), (4, 52))
        self.assertEqual(entry["surface_count"], 11)

    def test_unknown_code_falls_back_to_legacy(self) -> None:
        self.assertIsNone(find_profile("0" * 64))
        self.assertIsNone(find_profile("ff" * 64))

    def test_registry_matches_profile_file(self) -> None:
        entry = find_profile(KNOWN_CODE)
        assert entry is not None
        profile = json.loads(PROFILE.read_text())
        for key in ("code_sha256", "input_sha256", "zebin_sha256"):
            self.assertEqual(profile[key], entry[key])
        self.assertEqual(profile["expected_push_size"], entry["expected_push_size"])
        self.assertEqual(profile["table_pc_base"], entry["table_pc_base"])
        self.assertEqual(len(profile["surfaces"]), entry["surface_count"])
        self.assertTrue((ROOT / entry["profile"]).is_file())
        # Internal consistency enforced by tools/apply_cmk_mapping.convert.
        for index, surface in enumerate(profile["surfaces"]):
            self.assertEqual(surface["arg_index"], index)
            self.assertEqual(surface["push_byte_offset"],
                             entry["table_pc_base"] + 4 * surface["table_index"])

    def test_generation_digest_is_stable_and_content_bound(self) -> None:
        first = registry_gen()
        self.assertEqual(first, registry_gen(load()))
        self.assertRegex(first, r"^[0-9a-f]{8}$")
        mutated = load()
        mutated["profiles"][0]["expected_push_size"] = 56
        self.assertNotEqual(registry_gen(mutated), first)


@unittest.skipUnless((ROOT / "upstream/xess-xmx-linux/patches/0001-anv-cm-kernel-injection.patch").exists(),
                     "Optional upstream checkout absent")
class CacheIdentityTests(unittest.TestCase):
    def test_toolchain_gen_mixes_profile_digest_in_both_variants(self) -> None:
        from build_anv_mapping_patch import adapt
        expected = f"h = (h ^ 0x{registry_gen()}u) * 16777619u;"
        for relative in ("patches/0001-anv-cm-kernel-injection.patch",
                         "patches/mesa-26.3/0001-anv-cm-kernel-injection.patch"):
            original = (ROOT / "upstream/xess-xmx-linux" / relative).read_text()
            updated = adapt(original)
            self.assertIn(expected, updated)
            self.assertIn("LOCAL profile generation", updated)

    def test_checked_in_candidate_matches_generator(self) -> None:
        generated = subprocess.run(
            [sys.executable, str(ROOT / "tools/build_anv_mapping_patch.py"),
             str(ROOT / "upstream/xess-xmx-linux")],
            check=True, capture_output=True, text=True,
        ).stdout
        self.assertEqual(generated, PATCH.read_text())

    def test_legacy_cmk2_path_unchanged(self) -> None:
        from build_anv_mapping_patch import adapt
        original = (ROOT / "upstream/xess-xmx-linux/patches/0001-anv-cm-kernel-injection.patch").read_text()
        updated = adapt(original)
        # Legacy magic still accepted first; the tail heuristic is only
        # bypassed for explicit CMK3 files, so global XeSS behavior is kept.
        self.assertIn('memcmp(h.magic, "CMK2", 4) != 0 && memcmp(h.magic, "CMK3", 4) != 0', updated)
        self.assertIn("if (auto_heap && !explicit_table_base)", updated)


@unittest.skipUnless((ROOT / "upstream/xess-xmx-linux/patches/0001-anv-cm-kernel-injection.patch").exists(),
                     "Optional upstream checkout absent")
class ReaderValidationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler absent")
    def test_parametrized_base_and_push_validation(self) -> None:
        from build_anv_mapping_patch import adapt
        original = (ROOT / "upstream/xess-xmx-linux/patches/0001-anv-cm-kernel-injection.patch").read_text()
        added = "\n".join(line[1:] for line in adapt(original).splitlines()
                           if line.startswith("+") and not line.startswith("+++"))
        begin = added.index("   if (explicit_table_base) {")
        end = added.index("   if (cs->cm_has_sampler)", begin)
        block = added[begin:end]
        # (base, nsurf, table_idx, expected_size, ranges, expect_ok)
        cases = [
            # This PRE under the VKD3D reference layout: b0@0, 11 tables, sampler apart.
            (4, 11, list(range(11)), 52, [(0, 52)], True),
            (4, 11, list(range(11)), 52, [(0, 32), (32, 20)], True),
            # Wrong expected size, uncovered DWORD, out-of-range index.
            (4, 11, list(range(11)), 56, [(0, 52)], False),
            (4, 11, list(range(11)), 52, [(8, 44)], False),
            (4, 11, list(range(10)) + [12], 52, [(0, 52)], False),
            (4, 11, list(range(10)) + [0xFFFFFFFF], 52, [(0, 52)], False),
            (4, 11, list(range(11)), 52, [], False),
            (4, 11, list(range(11)), 52, [(0, 24), (28, 24)], False),
            # Coverage-based (not base-pinned); the file carries its own base.
            (8, 11, list(range(11)), 52, [(0, 52)], True),
            (4, 2, [0, 10], 52, [(0, 52)], True),
        ]
        lines = ["int main(void) {", "  int failures = 0;"]
        for number, (base, nsurf, idx, expected, ranges, ok) in enumerate(cases):
            idx_init = "".join(f"    h{number}.table_idx[{i}] = {v}u;\n" for i, v in enumerate(idx))
            range_init = "".join(
                f"    ranges{number}[{i}].offset = {o}; ranges{number}[{i}].size = {s};\n"
                for i, (o, s) in enumerate(ranges)
            ) or f"    (void)ranges{number};\n"
            lines.append(f"""\
  {{
    struct range ranges{number}[{max(len(ranges), 1)}];
    struct info ci{number} = {{{len(ranges)}, ranges{number}}};
    struct header h{number} = {{.table_pc_base = {base}, .nsurf = {nsurf}}};
{idx_init}{range_init}    int rc = validate(h{number}, {expected}, &ci{number});
    if ((rc == 0) != {str(ok).lower()}) {{ printf("case {number} rc=%d\\n", rc); failures++; }}
  }}""")
        lines.append("  return failures;\n}")
        harness = """#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <assert.h>
#define ANV_CM_FAILED -1
struct range { uint32_t offset, size; };
struct info { uint32_t push_constant_range_count; struct range *push_constant_ranges; };
struct header { uint32_t table_pc_base, nsurf, table_idx[24]; };
static int validate(struct header h, uint32_t expected, struct info *ci) {
 const bool explicit_table_base = true;
 uint32_t mapping[2] = {1, expected};
 int state = 7, saved = 7, *cs = &state;
 const char *path = "synthetic-test";
""" + block + """
 return 0;
}
""" + "\n".join(lines) + "\n"
        with tempfile.TemporaryDirectory(prefix="cmk-profile-test-") as temp:
            source = Path(temp) / "test.c"
            binary = Path(temp) / "test"
            source.write_text(harness)
            result = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                                     str(source), "-o", str(binary)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
