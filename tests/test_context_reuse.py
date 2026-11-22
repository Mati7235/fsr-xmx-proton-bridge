from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_context_output_patch as output_builder
import build_context_reuse_patch as reuse_builder

SOURCE = ROOT / "upstream/xess-xmx-linux/shim/src/dll/IgdextApiDll.cpp"
PATCH2 = ROOT / "patches/0002-shim-context-output.patch"
PATCH3 = ROOT / "patches/0003-shim-context-reuse.patch"
HEADER = ROOT / "upstream/xess-xmx-linux/shim/d3dext-sdk/include/public"
REVISION = "f06dc397375332d1b34e35b19227b86eceeddaab"
SOURCE_SHA256 = "8edbd9682c037d11f6c9b8fc358003ca99628f543505ab09ece3469d1b17fb48"


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
class ContextReusePatchTests(unittest.TestCase):
    def test_patch_is_reproducible_pinned_and_stacked(self) -> None:
        generated = subprocess.run(
            [sys.executable, str(ROOT / "tools/build_context_reuse_patch.py")],
            check=True, capture_output=True, text=True,
        ).stdout
        self.assertEqual(generated, PATCH3.read_text())
        self.assertEqual(
            hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            SOURCE_SHA256,
        )
        revision = subprocess.run(
            ["git", "-C", str(SOURCE.parents[3]), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(revision, REVISION)
        # The stacked builder must equal composing both layers explicitly.
        pristine = SOURCE.read_text()
        self.assertEqual(
            reuse_builder.build_full(pristine),
            reuse_builder.build(output_builder.build(pristine)),
        )

    def test_rejects_changed_upstream_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            modified = Path(temporary) / "IgdextApiDll.cpp"
            modified.write_bytes(SOURCE.read_bytes() + b"\n// changed\n")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/build_context_reuse_patch.py"),
                 "--source", str(modified)],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing unpinned source", result.stderr)

    def test_stack_applies_0002_then_0003(self) -> None:
        patch_tool = shutil.which("patch")
        self.assertIsNotNone(patch_tool, "patch utility is required for this test")
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            target = tree / "shim/src/dll/IgdextApiDll.cpp"
            target.parent.mkdir(parents=True)
            shutil.copyfile(SOURCE, target)
            for patch in (PATCH2, PATCH3):
                result = subprocess.run(
                    [patch_tool, "-p1", "--batch", "--forward", "-i", str(patch)],
                    cwd=tree,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            patched = target.read_text()
            self.assertIn("CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1)", patched)
            self.assertEqual(patched.count("D3D12ExtensionContext* const liveHalf"), 3)
            self.assertIn("*pExtensionInfo = reuseInfo1;", patched)
            self.assertIn("liveHalf->m_SupportedExtVersion = agreedVersion;", patched)

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

    def test_reuse_bodies_validate_device_version_and_refresh_outputs(self) -> None:
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ is required for CPU execution test")
        pristine = SOURCE.read_text()
        patched = reuse_builder.build_full(pristine)
        helper = extract_function(patched, "static void CopyExtensionInfo1OutputsToOld(")
        names = (
            "_INTC_D3D12_CreateDeviceExtensionContext(",
            "_INTC_D3D12_CreateDeviceExtensionContext1(",
            "_INTC_D3D12_CreateDeviceExtensionContext2(",
        )
        patched_bodies = "\n".join(extract_function(patched, f"HRESULT {n}") for n in names)
        harness = r'''
#define HRESULT int
#define BOOL int
typedef __SIZE_TYPE__ size_t;
#include "igdext.h"
using UINT32 = unsigned int;
static_assert(sizeof(INTCExtensionInfo) == 192, "host test must model Windows old layout");
static_assert(sizeof(INTCExtensionInfo1) == 200, "host test must model Windows extended layout");
constexpr HRESULT S_OK = 0, E_INVALIDARG = -1, E_OUTOFMEMORY = -2, E_FAIL = -3;
constexpr HRESULT E_NOINTERFACE = (HRESULT)0x80004002;
#define FAILED(hr) ((hr) < 0)
extern "C" void* memset(void*, int, size_t);
extern "C" int memcmp(const void*, const void*, size_t);
struct ID3D12Device {};
struct FakeComPtr { const ID3D12Device* p = nullptr; const ID3D12Device* Get() const { return p; } };
struct INTCExtensionVersionHelper : public INTCExtensionVersion {
    INTCExtensionVersionHelper() = default;
    INTCExtensionVersionHelper(const INTCExtensionVersion& r) {
        HWFeatureLevel = r.HWFeatureLevel; APIVersion = r.APIVersion; Revision = r.Revision;
    }
    bool IsSupported(const INTCExtensionVersionHelper& o) {
        return (HWFeatureLevel > o.HWFeatureLevel) ||
               (HWFeatureLevel == o.HWFeatureLevel && APIVersion > o.APIVersion) ||
               (HWFeatureLevel == o.HWFeatureLevel && APIVersion == o.APIVersion && Revision >= o.Revision);
    }
};
static const wchar_t driverDesc[] = L"shim driver";
static const wchar_t driverVersion[] = L"4.5";
static HRESULT initResult = S_OK;
struct D3D12ExtensionContext {
    FakeComPtr m_pAppDevice;
    INTCExtensionVersion m_SupportedExtVersion = {};
    HRESULT InitExtensions(const void* pDevice, void**, UINT32, INTCExtensionInfo1* info,
                           INTCExtensionAppInfo1*, bool = false) {
        if (initResult != S_OK) return initResult;
        if (info->RequestedExtensionVersion.HWFeatureLevel == 0 &&
            info->RequestedExtensionVersion.APIVersion == 0) return E_NOINTERFACE;
        INTCExtensionVersionHelper maxV; maxV.HWFeatureLevel = 5; maxV.APIVersion = 20; maxV.Revision = 0;
        if (!maxV.IsSupported(info->RequestedExtensionVersion)) return E_NOINTERFACE;
        m_pAppDevice.p = (const ID3D12Device*)pDevice;
        m_SupportedExtVersion = info->RequestedExtensionVersion;
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
        return S_OK;
    }
};
struct INTCExtensionContext { D3D12ExtensionContext* m_pD3D12ExtensionContext = nullptr; };
'''
        main = r'''
static bool versionEq(const INTCExtensionVersion& a, const INTCExtensionVersion& b) {
    return a.HWFeatureLevel == b.HWFeatureLevel && a.APIVersion == b.APIVersion && a.Revision == b.Revision;
}
struct Guarded { unsigned char before[16]; INTCExtensionInfo value; unsigned char after[16]; };
struct Guarded1 { unsigned char before[16]; INTCExtensionInfo1 value; unsigned char after[16]; };
static bool untouched(const unsigned char* b, const unsigned char* a) {
    for (int i = 0; i < 16; ++i) if (b[i] != 0xa5 || a[i] != 0x5a) return false;
    return true;
}
static INTCExtensionVersion V(const unsigned h, const unsigned a, const unsigned r) {
    INTCExtensionVersion v; v.HWFeatureLevel = h; v.APIVersion = a; v.Revision = r; return v;
}
int main() {
    // Harness helper must implement the granted>=requested partial order.
    {
        INTCExtensionVersionHelper g; g.HWFeatureLevel = 4; g.APIVersion = 20; g.Revision = 7;
        auto sup = [&](unsigned h, unsigned a, unsigned r) {
            INTCExtensionVersionHelper o; o.HWFeatureLevel = h; o.APIVersion = a; o.Revision = r;
            return g.IsSupported(o);
        };
        if (!sup(4,20,7) || !sup(4,20,0) || !sup(4,19,9) || !sup(3,99,99)) return 20;
        if (sup(4,20,8) || sup(5,20,0) || sup(4,21,0)) return 21;
    }
    ID3D12Device device, other;
    const INTCExtensionVersion granted = V(4,20,7);
    for (int api = 0; api != 2; ++api) {
        Guarded out; memset(&out, 0, sizeof(out));
        memset(out.before, 0xa5, sizeof(out.before)); memset(out.after, 0x5a, sizeof(out.after));
        out.value.RequestedExtensionVersion = granted; out.value.DeviceDriverBuildNumber = 12;
        INTCExtensionContext* ctx = nullptr;
        HRESULT hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &out.value, nullptr)
                         : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &out.value, nullptr);
        if (hr != S_OK || !ctx || !untouched(out.before, out.after)) return 1;
#ifndef SKIP_INIT_OUTPUTS
        if (out.value.IntelDeviceInfo.GPUMaxFreq != 2500 || out.value.pDeviceDriverDesc != driverDesc ||
            out.value.DeviceDriverBuildNumber != 9876) return 2;
#endif
        auto stored = [&] { return ctx->m_pD3D12ExtensionContext->m_SupportedExtVersion; };
        if (!versionEq(stored(), granted)) return 10;
        // Reuse with a fresh struct, same device and version: must refresh outputs.
        Guarded fresh; memset(&fresh, 0, sizeof(fresh));
        memset(fresh.before, 0xa5, sizeof(fresh.before)); memset(fresh.after, 0x5a, sizeof(fresh.after));
        fresh.value.RequestedExtensionVersion = granted; fresh.value.DeviceDriverBuildNumber = 12;
        Guarded freshSnapshot = fresh;
        hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &fresh.value, nullptr)
                 : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &fresh.value, nullptr);
        if (hr != S_OK) return 5;
        if (memcmp(&fresh, &freshSnapshot, sizeof(fresh)) == 0) return 6; // no refresh happened
        if (fresh.value.IntelDeviceInfo.GPUMaxFreq != 2500 || fresh.value.pDeviceDriverDesc != driverDesc ||
            fresh.value.pDeviceDriverVersion != driverVersion || fresh.value.DeviceDriverBuildNumber != 9876 ||
            fresh.value.IntelDeviceInfo.GTGenerationName[0] != L'Z' ||
            memcmp(&fresh.value.RequestedExtensionVersion, &granted, sizeof(granted))) return 7;
        if (!untouched(fresh.before, fresh.after)) return 8;
        if (!versionEq(stored(), granted)) return 11; // live contract must not move
        // Reuse with a lower version: still compatible, contract unchanged.
        Guarded lower = fresh; lower.value.RequestedExtensionVersion = V(4,19,9);
        lower.value.IntelDeviceInfo.GPUMaxFreq = 0; lower.value.DeviceDriverBuildNumber = 0;
        hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &lower.value, nullptr)
                 : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &lower.value, nullptr);
        if (hr != S_OK || lower.value.IntelDeviceInfo.GPUMaxFreq != 2500) return 12;
        if (!versionEq(stored(), granted)) return 13; // no silent downgrade of the live half
        // Reuse with a higher version: must fail and leave the caller untouched.
        Guarded higher; memset(&higher, 0, sizeof(higher));
        memset(higher.before, 0xa5, sizeof(higher.before)); memset(higher.after, 0x5a, sizeof(higher.after));
        higher.value.RequestedExtensionVersion = V(4,20,8); higher.value.DeviceDriverBuildNumber = 12;
        Guarded higherSnapshot = higher;
        hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &higher.value, nullptr)
                 : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &higher.value, nullptr);
        if (hr != E_NOINTERFACE) return 14;
        if (memcmp(&higher, &higherSnapshot, sizeof(higher))) return 15;
        if (!versionEq(stored(), granted)) return 16;
        // Reuse from another device: must fail and leave the caller untouched.
        Guarded foreign = higher; foreign.value.RequestedExtensionVersion = granted;
        Guarded foreignSnapshot = foreign;
        hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&other, &ctx, &foreign.value, nullptr)
                 : _INTC_D3D12_CreateDeviceExtensionContext(&other, &ctx, &foreign.value, nullptr);
        if (hr != E_INVALIDARG) return 17;
        if (memcmp(&foreign, &foreignSnapshot, sizeof(foreign))) return 18;
        // Live-half refresh failure (e.g. fallback flip): error, caller untouched, half alive.
        initResult = E_FAIL;
        Guarded failing = higher; failing.value.RequestedExtensionVersion = granted;
        Guarded failingSnapshot = failing;
        INTCExtensionContext* beforeCtx = ctx;
        hr = api ? _INTC_D3D12_CreateDeviceExtensionContext1(&device, &ctx, &failing.value, nullptr)
                 : _INTC_D3D12_CreateDeviceExtensionContext(&device, &ctx, &failing.value, nullptr);
        initResult = S_OK;
        if (hr != E_FAIL || ctx != beforeCtx) return 19;
        if (memcmp(&failing, &failingSnapshot, sizeof(failing))) return 22;
        if (!versionEq(stored(), granted)) return 23;
        delete ctx->m_pD3D12ExtensionContext; delete ctx;
    }
    // Context2 carries the full Info1 width: refresh must include the GMD tail.
    {
        Guarded1 out; memset(&out, 0, sizeof(out));
        memset(out.before, 0xa5, sizeof(out.before)); memset(out.after, 0x5a, sizeof(out.after));
        out.value.RequestedExtensionVersion = granted;
        INTCExtensionContext* ctx = nullptr;
        HRESULT hr = _INTC_D3D12_CreateDeviceExtensionContext2(&device, &ctx, &out.value, nullptr);
        if (hr != S_OK || !ctx) return 30;
#ifndef SKIP_INIT_OUTPUTS
        if (out.value.IntelDeviceInfo.GMDID != 0xabcdef01 ||
            out.value.IntelDeviceInfo.XeCoresCount != 64) return 30;
#endif
        Guarded1 fresh; memset(&fresh, 0, sizeof(fresh));
        memset(fresh.before, 0xa5, sizeof(fresh.before)); memset(fresh.after, 0x5a, sizeof(fresh.after));
        fresh.value.RequestedExtensionVersion = granted;
        Guarded1 freshSnapshot = fresh;
        hr = _INTC_D3D12_CreateDeviceExtensionContext2(&device, &ctx, &fresh.value, nullptr);
        if (hr != S_OK || memcmp(&fresh, &freshSnapshot, sizeof(fresh)) == 0) return 31;
        if (fresh.value.IntelDeviceInfo.GMDID != 0xabcdef01 || fresh.value.IntelDeviceInfo.XeCoresCount != 64 ||
            fresh.value.pDeviceDriverDesc != driverDesc || fresh.value.DeviceDriverBuildNumber != 9876) return 32;
        Guarded1 higher = fresh; higher.value.RequestedExtensionVersion = V(5,20,0);
        Guarded1 higherSnapshot = higher;
        hr = _INTC_D3D12_CreateDeviceExtensionContext2(&device, &ctx, &higher.value, nullptr);
        if (hr != E_NOINTERFACE || memcmp(&higher, &higherSnapshot, sizeof(higher))) return 33;
        Guarded1 foreign = fresh; Guarded1 foreignSnapshot = foreign;
        hr = _INTC_D3D12_CreateDeviceExtensionContext2(&other, &ctx, &foreign.value, nullptr);
        if (hr != E_INVALIDARG || memcmp(&foreign, &foreignSnapshot, sizeof(foreign))) return 34;
        delete ctx->m_pD3D12ExtensionContext; delete ctx;
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
            original_bodies = "\n".join(extract_function(pristine, f"HRESULT {n}") for n in names)
            for name, tested_bodies, expected_exit, extra_flags in (
                ("patched", patched_bodies, 0, []),
                # The original init path never copies outputs, so skip the init
                # value checks and characterize the reuse path: S_OK, no refresh.
                ("original-regression", original_bodies, 6, ["-DSKIP_INIT_OUTPUTS"]),
            ):
                with self.subTest(implementation=name):
                    test_source = root / (name + ".cpp")
                    test_source.write_text(harness + helper + tested_bodies + main)
                    executable = root / name
                    result = subprocess.run(
                        [compiler, "-std=c++17", "-fshort-wchar", "-nostdinc++", "-I" + str(root),
                         "-I" + str(HEADER), str(test_source), "-o", str(executable)] + extra_flags,
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    run = subprocess.run([str(executable)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, expected_exit, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
