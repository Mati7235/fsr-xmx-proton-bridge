"""Bridge-regen gates for the XMX 4.1.2 recheck (CPU-only).

Covers, without executing DLLs, GPU, Wine, prefixes, installs, or upstream
mutation:

- determinism of the three builders against the checked-in patches;
- pinned upstream revision/source for the shim builders;
- ``git apply --check`` for 0001 plus the stacked 0002 -> 0003 application;
- acceptance of a synthetic second registry entry by
  ``tools/pre_profile_registry.py`` + ``tools/build_anv_mapping_patch.py``
  with no code change (fail-closed for the real REQUIRED-TBD fragment).

The synthetic second entry is NOT a 4.1.2 pin: its digests are placeholders
(``ab/cd/ef * 32``) and its profile path reuses the existing reviewed file
only to satisfy the ``load()`` existence check without creating repo files.
Real 4.1.2 promotion stays blocked until ``profiles/xmx412-pins.json``
resolves every REQUIRED-TBD (see docs/shim-bridge.md).
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from pre_profile_registry import find_profile, load, registry_gen  # noqa: E402

SOURCE = ROOT / "upstream/xess-xmx-linux/shim/src/dll/IgdextApiDll.cpp"
HEADER = ROOT / "upstream/xess-xmx-linux/shim/d3dext-sdk/include/public"
PATCH1 = ROOT / "patches/0001-anv-cmk3-explicit-mapping.patch"
PATCH2 = ROOT / "patches/0002-shim-context-output.patch"
PATCH3 = ROOT / "patches/0003-shim-context-reuse.patch"
BUILDER2 = ROOT / "tools/build_context_output_patch.py"
BUILDER3 = ROOT / "tools/build_context_reuse_patch.py"
REGISTRY = ROOT / "profiles/registry.json"
PINS = ROOT / "profiles/xmx412-pins.json"
UPSTREAM = ROOT / "upstream/xess-xmx-linux"
REVISION = "f06dc397375332d1b34e35b19227b86eceeddaab"
SOURCE_SHA256 = "8edbd9682c037d11f6c9b8fc358003ca99628f543505ab09ece3469d1b17fb48"
KNOWN_CODE = "2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f"

# Synthetic placeholder digests: well-formed but NOT 4.1.2 pins.
SYN_CODE = "ab" * 32
SYN_INPUT = "cd" * 32
SYN_ZEBIN = "ef" * 32


def synthetic_two_entry_registry() -> dict:
    """Real registry plus one synthetic, well-formed second entry."""
    base = copy.deepcopy(load())
    base["profiles"].append({
        "kernel": "fsr4_pre_xmx",
        "variant": "synthetic-412-native1080",
        "code_sha256": SYN_CODE,
        "input_sha256": SYN_INPUT,
        "zebin_sha256": SYN_ZEBIN,
        "profile": "profiles/fsr4-pre-native1080-bmg.json",
        "table_pc_base": 8,
        "expected_push_size": 56,
        "surface_count": 11,
    })
    return base


@unittest.skipUnless(SOURCE.is_file(), "Requires the pinned local upstream checkout")
class BuilderDeterminismTests(unittest.TestCase):
    def test_0002_reproducible_and_pinned(self) -> None:
        generated = subprocess.run(
            [sys.executable, str(BUILDER2)], check=True,
            capture_output=True, text=True).stdout
        self.assertEqual(generated, PATCH2.read_text())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), SOURCE_SHA256)
        revision = subprocess.run(
            ["git", "-C", str(SOURCE.parents[3]), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(revision, REVISION)

    def test_0003_reproducible_pinned_and_stacked(self) -> None:
        generated = subprocess.run(
            [sys.executable, str(BUILDER3)], check=True,
            capture_output=True, text=True).stdout
        self.assertEqual(generated, PATCH3.read_text())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), SOURCE_SHA256)
        revision = subprocess.run(
            ["git", "-C", str(SOURCE.parents[3]), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(revision, REVISION)
        import build_context_output_patch as output_builder
        import build_context_reuse_patch as reuse_builder
        pristine = SOURCE.read_text()
        self.assertEqual(reuse_builder.build_full(pristine),
                         reuse_builder.build(output_builder.build(pristine)))

    def test_builders_refuse_modified_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            modified = Path(temporary) / "IgdextApiDll.cpp"
            modified.write_bytes(SOURCE.read_bytes() + b"\n// changed\n")
            for builder in (BUILDER2, BUILDER3):
                result = subprocess.run(
                    [sys.executable, str(builder), "--source", str(modified)],
                    capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("refusing unpinned source", result.stderr)

    @unittest.skipUnless((UPSTREAM / "patches/0001-anv-cm-kernel-injection.patch").is_file(),
                         "Optional upstream Mesa patch absent")
    def test_0001_reproducible(self) -> None:
        generated = subprocess.run(
            [sys.executable, str(ROOT / "tools/build_anv_mapping_patch.py"), str(UPSTREAM)],
            check=True, capture_output=True, text=True).stdout
        self.assertEqual(generated, PATCH1.read_text())


@unittest.skipUnless(SOURCE.is_file(), "Requires the pinned local upstream checkout")
class PatchApplyTests(unittest.TestCase):
    def test_0001_git_apply_check(self) -> None:
        result = subprocess.run(
            ["git", "-C", str(UPSTREAM), "apply", "--check", str(PATCH1)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_0002_git_apply_check(self) -> None:
        result = subprocess.run(
            ["git", "-C", str(UPSTREAM), "apply", "--check", str(PATCH2)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stack_0002_then_0003_applies_p1(self) -> None:
        tool = shutil.which("patch")
        self.assertIsNotNone(tool)
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            target = tree / "shim/src/dll/IgdextApiDll.cpp"
            target.parent.mkdir(parents=True)
            shutil.copyfile(SOURCE, target)
            for patch_file in (PATCH2, PATCH3):
                result = subprocess.run(
                    [tool, "-p1", "--batch", "--forward", "-i", str(patch_file)],
                    cwd=tree, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            patched = target.read_text()
            self.assertIn("CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1)", patched)
            self.assertEqual(patched.count("D3D12ExtensionContext* const liveHalf"), 3)


class RegistryTwoEntryTests(unittest.TestCase):
    def test_real_registry_has_two_reviewed_entries(self) -> None:
        registry = load()
        self.assertEqual(len(registry["profiles"]), 2)
        self.assertEqual(registry_gen(), "3ddd809f")

    def test_synthetic_third_entry_loads_without_code_change(self) -> None:
        candidate = synthetic_two_entry_registry()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
            path = Path(handle.name)
        try:
            path.write_text(json.dumps(candidate))
            loaded = load(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(loaded["profiles"]), 3)
        self.assertIsNotNone(find_profile(KNOWN_CODE, loaded))
        second = find_profile(SYN_CODE, loaded)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual((second["table_pc_base"], second["expected_push_size"]), (8, 56))

    def test_generation_changes_and_is_content_bound(self) -> None:
        candidate = synthetic_two_entry_registry()
        new_gen = registry_gen(candidate)
        self.assertRegex(new_gen, r"^[0-9a-f]{8}$")
        self.assertNotEqual(new_gen, registry_gen())
        self.assertEqual(new_gen, registry_gen(copy.deepcopy(candidate)))
        mutated = copy.deepcopy(candidate)
        mutated["profiles"][1]["expected_push_size"] = 60
        self.assertNotEqual(registry_gen(mutated), new_gen)

    def test_unknown_digests_still_miss_with_two_entries(self) -> None:
        candidate = synthetic_two_entry_registry()
        self.assertIsNone(find_profile("00" * 64, candidate))
        self.assertIsNone(find_profile("ff" * 64, candidate))
        self.assertIsNone(find_profile("REQUIRED-TBD", candidate))

    @unittest.skipUnless((UPSTREAM / "patches/0001-anv-cm-kernel-injection.patch").is_file(),
                         "Optional upstream Mesa patch absent")
    def test_mapping_builder_embeds_new_generation_without_code_change(self) -> None:
        import build_anv_mapping_patch as mapping
        candidate = synthetic_two_entry_registry()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
            path = Path(handle.name)
        try:
            path.write_text(json.dumps(candidate))
            loaded = load(path)
        finally:
            path.unlink(missing_ok=True)
        original = (UPSTREAM / "patches/0001-anv-cm-kernel-injection.patch").read_text()
        with mock_patch.object(mapping, "load_registry", return_value=loaded):
            adapted = mapping.adapt(original)
        new_needle = "h = (h ^ 0x" + registry_gen(loaded) + "u)"
        old_needle = "h = (h ^ 0x" + registry_gen() + "u)"
        self.assertIn(new_needle, adapted)
        self.assertNotIn(old_needle, adapted)
        self.assertIn("LOCAL profile generation", adapted)


class FailClosedTests(unittest.TestCase):
    def test_pins_fragment_is_still_tbd_and_rejected(self) -> None:
        pins = json.loads(PINS.read_text())
        self.assertEqual(pins["status"], "staging-only-not-for-registry")
        fragment = dict(pins["future_registry_entry_fragment"])
        fragment.pop("_comment", None)
        for key in ("code_sha256", "input_sha256", "zebin_sha256", "variant",
                    "table_pc_base", "expected_push_size", "surface_count", "profile"):
            self.assertEqual(fragment[key], "REQUIRED-TBD")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "status": "experimental-offline-only",
                "profiles": [fragment],
            }))
            with self.assertRaises(ValueError):
                load(path)

    def test_no_412_code_in_real_registry(self) -> None:
        pins = json.loads(PINS.read_text())
        registry = load()
        for pack in pins["packs"]:
            self.assertIsNone(find_profile(pack["raw_sha256"], registry))
        self.assertIsNone(find_profile(SYN_CODE, registry))

    def test_duplicate_code_rejected(self) -> None:
        candidate = synthetic_two_entry_registry()
        candidate["profiles"][1]["code_sha256"] = KNOWN_CODE
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "status": "experimental-offline-only",
                "profiles": candidate["profiles"],
            }))
            with self.assertRaises(ValueError):
                load(path)

    def test_misaligned_layout_rejected(self) -> None:
        candidate = synthetic_two_entry_registry()
        candidate["profiles"][1]["table_pc_base"] = 5
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "status": "experimental-offline-only",
                "profiles": candidate["profiles"],
            }))
            with self.assertRaises(ValueError):
                load(path)

    def test_missing_profile_file_rejected(self) -> None:
        candidate = synthetic_two_entry_registry()
        candidate["profiles"][1]["profile"] = "profiles/does-not-exist-412.json"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "status": "experimental-offline-only",
                "profiles": candidate["profiles"],
            }))
            with self.assertRaises(ValueError):
                load(path)


if __name__ == "__main__":
    unittest.main()
