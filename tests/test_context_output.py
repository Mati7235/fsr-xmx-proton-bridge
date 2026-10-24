from __future__ import annotations

import hashlib
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "upstream/xess-xmx-linux/shim/src/dll/IgdextApiDll.cpp"
PATCH = ROOT / "patches/0002-shim-context-output.patch"
BUILDER = ROOT / "tools/build_context_output_patch.py"
HEADER = ROOT / "upstream/xess-xmx-linux/shim/d3dext-sdk/include/public"
REVISION = "ef39559d26e083ce1bd1353b2e8c86f33c3c264c"
SOURCE_SHA256 = "aed09d4fc616721216a46654b1501a6a2f7b93c0c198523f41fdba327c80ca96"


def extract_function(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated function: {signature}")


@unittest.skipUnless(SOURCE.is_file() and (HEADER / 'igdext.h').is_file(),
                     'Requires the pinned local upstream checkout')
class ContextOutputPatchTests(unittest.TestCase):
    def test_patch_is_reproducible_and_pinned(self) -> None:
        generated = subprocess.run(
            [sys.executable, str(BUILDER)], check=True, capture_output=True, text=True
        ).stdout
        self.assertEqual(generated, PATCH.read_text())
        self.assertEqual(
            hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            SOURCE_SHA256,
        )
        revision = subprocess.run(
            ["git", "-C", str(SOURCE.parents[3]), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(revision, REVISION)

    def test_rejects_changed_upstream_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            modified = Path(temporary) / "IgdextApiDll.cpp"
            modified.write_bytes(SOURCE.read_bytes() + b"\n// changed\n")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--source", str(modified)],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing unpinned source", result.stderr)

    def test_patch_applies_to_pinned_revision(self) -> None:
        patch_tool = shutil.which("patch")
        self.assertIsNotNone(patch_tool, "patch utility is required for this test")
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            target = tree / "shim/src/dll/IgdextApiDll.cpp"
            target.parent.mkdir(parents=True)
            shutil.copyfile(SOURCE, target)
            result = subprocess.run(
                [patch_tool, "-p1", "--batch", "--forward", "-i", str(PATCH)],
                cwd=tree,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            patched = target.read_text()
            self.assertIn("CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1)", patched)
            self.assertEqual(patched.count("InitExtensions(pDevice, nullptr, 0, &extensionInfo1,"), 2)

    def test_windows_abi_layout_against_real_header(self) -> None:
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ is required for the Windows ABI check")
        code = r'''
#define HRESULT int
#define BOOL int
typedef __SIZE_TYPE__ size_t;
#include "igdext.h"
static_assert(sizeof(void*) == 8, "64-bit Windows ABI");
static_assert(sizeof(wchar_t) == 2, "Windows wchar_t ABI");
static_assert(sizeof(INTCExtensionInfo) == 192, "old ABI size");
static_assert(sizeof(INTCExtensionInfo1) == 200, "extended ABI size");
static_assert(__builtin_offsetof(INTCExtensionInfo, IntelDeviceInfo) == 12, "old device offset");
static_assert(__builtin_offsetof(INTCExtensionInfo1, IntelDeviceInfo) == 12, "new device offset");
static_assert(__builtin_offsetof(INTCExtensionInfo, pDeviceDriverDesc) == 168, "old output offset");
static_assert(__builtin_offsetof(INTCExtensionInfo1, pDeviceDriverDesc) == 176, "new output offset");
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "stdint.h").write_text(
                "typedef unsigned char uint8_t; typedef unsigned int uint32_t; "
                "typedef int int32_t; typedef unsigned long long uint64_t;\n"
            )
            source = root / "abi.cpp"
            source.write_text(code)
            result = subprocess.run(
                [compiler, "-target", "x86_64-pc-windows-msvc", "-std=c++17",
                 "-fsyntax-only", "-nostdinc", f"-I{root}", f"-I{HEADER}", str(source)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_d3d12_bodies_copy_success_outputs_without_overflow(self) -> None:
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ is required for CPU execution test")
        source_text = SOURCE.read_text()
        patched = runpy.run_path(str(BUILDER))["build"](source_text)
        helper = extract_function(patched, "static void CopyExtensionInfo1OutputsToOld(")
        bodies = "\n".join(extract_function(patched, f"HRESULT {name}(") for name in (
            "_INTC_D3D12_CreateDeviceExtensionContext",
            "_INTC_D3D12_CreateDeviceExtensionContext1",
        ))
        harness = r'''
#define HRESULT int
#define BOOL int
typedef __SIZE_TYPE__ size_t;
#include "igdext.h"
using UINT32 = unsigned int;
static_assert(sizeof(INTCExtensionInfo) == 192, "host test must model Windows old layout");
static_assert(sizeof(INTCExtensionInfo1) == 200, "host test must model Windows extended layout");
constexpr HRESULT S_OK = 0, E_INVALIDARG = -1, E_OUTOFMEMORY = -2, E_FAIL = -3;
#define FAILED(hr) ((hr) < 0)
extern "C" void* memset(void*, int, size_t);
extern "C" int memcmp(const void*, const void*, size_t);
struct ID3D12Device {};
struct INTCExtensionContext;
static const wchar_t driverDesc[] = L"shim driver";
static const wchar_t driverVersion[] = L"4.5";
static HRESULT initResult = S_OK;
static INTCExtensionVersion expectedVersion = {4, 20, 7};
struct D3D12ExtensionContext {
    HRESULT InitExtensions(const void*, void**, UINT32, INTCExtensionInfo1* info,
                           INTCExtensionAppInfo1*) {
        if (info->RequestedExtensionVersion.HWFeatureLevel != expectedVersion.HWFeatureLevel ||
            info->RequestedExtensionVersion.APIVersion != expectedVersion.APIVersion ||
            info->RequestedExtensionVersion.Revision != expectedVersion.Revision) return E_FAIL;
        info->IntelDeviceInfo.GPUMaxFreq = 2500;
        info->IntelDeviceInfo.GPUMinFreq = 300;
        info->IntelDeviceInfo.GTGeneration = 20;
        info->IntelDeviceInfo.EUCount = 128;
        info->IntelDeviceInfo.PackageTDP = 225;
        info->IntelDeviceInfo.MaxFillRate = 32;
        info->IntelDeviceInfo.GTGenerationName[0] = L'Z';
        info->IntelDeviceInfo.GTGenerationName[63] = L'Q';
        info->IntelDeviceInfo.GMDID = 0xabcdef01;
        info->IntelDeviceInfo.XeCoresCount = 64;
        info->pDeviceDriverDesc = driverDesc;
        info->pDeviceDriverVersion = driverVersion;
        info->DeviceDriverBuildNumber = 9876;
        return initResult;
    }
};
struct INTCExtensionContext { D3D12ExtensionContext* m_pD3D12ExtensionContext = nullptr; };
'''
        main = r'''
struct Guarded { unsigned char before[16]; INTCExtensionInfo value; unsigned char after[16]; };
static bool untouched(const Guarded& g) {
    for (auto c : g.before) if (c != 0xa5) return false;
    for (auto c : g.after) if (c != 0x5a) return false;
    return true;
}
static void seed(Guarded& g) {
    memset(&g, 0, sizeof(g));
    memset(g.before, 0xa5, sizeof(g.before));
    memset(g.after, 0x5a, sizeof(g.after));
    g.value.RequestedExtensionVersion = expectedVersion;
    g.value.DeviceDriverBuildNumber = 12;
}
int main() {
    ID3D12Device device;
    for (int api = 0; api != 2; ++api) {
        Guarded out; seed(out); INTCExtensionContext* ctx = nullptr;
        HRESULT hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &out.value, nullptr)
                         : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &out.value, nullptr);
        if (hr != S_OK || !ctx || !untouched(out)) return 1;
         if (out.value.IntelDeviceInfo.GPUMaxFreq != 2500 ||
            out.value.IntelDeviceInfo.GPUMinFreq != 300 ||
            out.value.IntelDeviceInfo.GTGeneration != 20 ||
            out.value.IntelDeviceInfo.EUCount != 128 ||
            out.value.IntelDeviceInfo.PackageTDP != 225 ||
            out.value.IntelDeviceInfo.MaxFillRate != 32 ||
            out.value.IntelDeviceInfo.GTGenerationName[0] != L'Z' ||
            out.value.IntelDeviceInfo.GTGenerationName[63] != L'Q' ||
            out.value.pDeviceDriverDesc != driverDesc ||
             out.value.pDeviceDriverVersion != driverVersion ||
             out.value.DeviceDriverBuildNumber != 9876) return 2;
         if (memcmp(&out.value.RequestedExtensionVersion, &expectedVersion, sizeof(expectedVersion))) return 4;
         delete ctx->m_pD3D12ExtensionContext; delete ctx;
         seed(out); initResult = E_FAIL; ctx = nullptr;
         Guarded snapshot = out;
        hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &out.value, nullptr)
                 : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &out.value, nullptr);
         if (hr != E_FAIL || ctx || !untouched(out) || out.value.DeviceDriverBuildNumber != 12) return 3;
         if (memcmp(&out, &snapshot, sizeof(out))) return 5;
         initResult = S_OK;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "stdint.h").write_text(
                "typedef unsigned char uint8_t; typedef unsigned int uint32_t; "
                "typedef int int32_t; typedef unsigned long long uint64_t;\n"
            )
            original_bodies = "\n".join(extract_function(source_text, f"HRESULT {name}(") for name in (
                "_INTC_D3D12_CreateDeviceExtensionContext",
                "_INTC_D3D12_CreateDeviceExtensionContext1",
            ))
            for name, tested_bodies, expected_exit in (
                ("patched", bodies, 0), ("original-regression", original_bodies, 2),
            ):
                with self.subTest(implementation=name):
                    test_source = root / (name + ".cpp")
                    test_source.write_text(harness + helper + tested_bodies + main)
                    executable = root / name
                    result = subprocess.run(
                        [compiler, "-std=c++17", "-fshort-wchar", "-nostdinc++", "-I" + str(root),
                         "-I" + str(HEADER), str(test_source), "-o", str(executable)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    run = subprocess.run([str(executable)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, expected_exit, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
