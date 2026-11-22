#!/usr/bin/env python3
"""Build the minimal amdxc64.dll gate shim (CPU-only research, P0 probe).

The FG 4.0.1 module (amd_fidelityfx_framegeneration_dx12.dll) only selects its
internal ML path when it can load amdxc64.dll and answer three queries
(analysis/fg-401-static/amdxc-gate.md):

  AmdExtD3DCreateInterface(device, IID_IAmdExtD3DFactory)
    -> factory->CreateInterface(device, IID_IAmdExtD3DDevice8)
       -> Device8->GetWaveMatrixProperties(&count, props)
            entry: 16x16x16, aType=bType=fp8(0xB), cType=resultType=f32(1)
    -> factory->CreateInterface(device, IID_IAmdExtD3DShaderIntrinsics)
       -> CheckSupport(0x1F WaveMatrix), CheckSupport(0x20 Float8Conversion)
       -> Enable()
  (IAmdExtFfxApi is answered E_NOINTERFACE: the DLL's provider memcmp treats
   it exactly like an empty provider.)

This script compiles the embedded C source with the local LLVM-MinGW toolchain
into build/amdxc64-shim/amdxc64.dll. The DLL imports only KERNEL32, exports the
five names of Proton's wine stub, keeps static singleton objects and logs every
call to the file named by AMDXC_SHIM_LOG (off by default). It is inert unless
AMDXC_SHIM is set to a non-"0" value.

Also builds a host twin (same source, logging to stdio, -DAMDXC_HOST_TEST) at
build/amdxc64-shim/test/libamdxc64_shim_test.so so the ABI behaviour can be
exercised via ctypes without Wine.

Safety boundaries (fail closed):
  * writes only under build/amdxc64-shim/;
  * never executes the produced DLL, Wine, a game, or the target module;
  * only compile + link + static inspection (readobj/objdump);
  * no Steam/prefix/Proton/driver state is touched.

Usage:
  python3 tools/build_amdxc64_shim.py [--windows-only | --host-only |
                                      --verify-only]
"""

import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "amdxc64-shim"
SRC_DIR = BUILD_DIR / "src"
OBJ_DIR = BUILD_DIR / "obj"
TEST_DIR = BUILD_DIR / "test"

TOOLCHAIN = (ROOT / "artifacts" / "extracted" / "llvm-mingw-20261020-ucrt" /
             "llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64")
CLANG = TOOLCHAIN / "bin" / "x86_64-w64-mingw32-clang"
READOBJ = TOOLCHAIN / "bin" / "llvm-readobj"
OBJDUMP = TOOLCHAIN / "bin" / "x86_64-w64-mingw32-objdump"

EXPECTED_EXPORTS = [
    "AmdExtD3DCreateInterface",
    "AmdGetDxcModuleHandle",
    "GetSettingsBlobsAll",
    "OpenAdapter12",
    "OpenShimInterface",
]
ALLOWED_IMPORT_DLLS = {"KERNEL32.dll"}
# Strings that must survive in the binary: env names are UTF-16 (used with the
# W APIs), method names are ASCII. Accept either encoding.
EXPECTED_STRINGS = [b"AMDXC_SHIM_LOG", b"AMDXC_SHIM", b"GetWaveMatrixProperties",
                    b"CheckSupport", b"AmdExtD3DCreateInterface"]

AMDXC64_DEF = """LIBRARY amdxc64
EXPORTS
AmdExtD3DCreateInterface
AmdGetDxcModuleHandle
GetSettingsBlobsAll
OpenAdapter12
OpenShimInterface
"""

AMDXC64_SHIM_C = r'''/*
 * amdxc64_shim.c - Minimal amdxc64.dll for the FSR FG 4.0.1 ML gate probe.
 *
 * Design: analysis/fg-401-static/amdxc-gate.md. It answers only what the FG
 * module asks for, with static singleton objects, and logs every call.
 *
 * Answers:
 *   IAmdExtD3DFactory          014937EC-9288-446F-A9AC-D75A8E3A984F
 *     CreateInterface -> IAmdExtD3DDevice8      F714E11A-...
 *                     -> IAmdExtD3DShaderIntrinsics BA019D53-...
 *   Device8::GetWaveMatrixProperties returns the single accepted entry:
 *     16x16x16, aType=bType=0xB (fp8), cType=resultType=0x1 (f32), sat=0
 *   ShaderIntrinsics::CheckSupport/Enable return S_OK.
 *   IAmdExtFfxApi  B58D6601-... -> UpdateFfxApiProvider returns E_NOINTERFACE
 *     (identical to an empty provider: the module memcmp()s it away).
 *
 * The object is inert unless AMDXC_SHIM is set to a value other than "0".
 * Logging goes to AMDXC_SHIM_LOG (append) when set, KERNEL32 only.
 *
 * Research code, CPU-only inspection. It is never executed by the build.
 */

#if defined(AMDXC_HOST_TEST)
#  include <stdio.h>
#  include <stdlib.h>
#  include <string.h>
#  define SHIM_EXPORT __attribute__((visibility("default")))
#  define SHIM_CALL
typedef unsigned int shim_u32;
typedef unsigned long long shim_u64;
typedef int shim_i32;
typedef void *shim_handle;
#else
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#  define SHIM_EXPORT __declspec(dllexport)
#  define SHIM_CALL __stdcall
typedef UINT32 shim_u32;
typedef UINT64 shim_u64;
typedef INT32 shim_i32;
typedef HANDLE shim_handle;
#endif

#define S_OK_        0
#define E_NOTIMPL_   ((shim_i32)0x80004001)
#define E_NOINTERFACE_ ((shim_i32)0x80004002)
#define E_POINTER_   ((shim_i32)0x80004003)

typedef struct {
    shim_u32 d1;
    unsigned short d2;
    unsigned short d3;
    unsigned char d4[8];
} shim_guid;

/* IIDs from the target module (RVA 0x10EE30 / 0x2608200 / 0x2608210 /
 * 0x2608220); constants repeated here so the shim does not depend on any
 * vendor header. */
static const shim_guid IID_FfxApi = {
    0xB58D6601u, 0x7401u, 0x4234u, {0x81, 0x80, 0x6F, 0xEB, 0xFC, 0x0E, 0x48, 0x4C}};
static const shim_guid IID_ShaderIntrinsics = {
    0xBA019D53u, 0xCCABu, 0x4CBDu, {0xB5, 0x6A, 0x72, 0x30, 0xED, 0x43, 0x30, 0xAD}};
static const shim_guid IID_Device8 = {
    0xF714E11Au, 0xB54Eu, 0x4E0Fu, {0xAB, 0xC5, 0xDF, 0x58, 0xB1, 0x81, 0x33, 0xD1}};
static const shim_guid IID_Factory = {
    0x014937ECu, 0x9288u, 0x446Fu, {0xA9, 0xAC, 0xD7, 0x5A, 0x8E, 0x3A, 0x98, 0x4F}};
static const shim_guid IID_FlipMeter = {
    0x543820DDu, 0x06C9u, 0x4F7Eu, {0xA3, 0xD0, 0xCA, 0x26, 0x0D, 0x79, 0x4A, 0xDD}};

/* Wave matrix property types, from the FFX 2.1 PDBs (OptiScaler header). */
#define WMMA_FP8 0xBu
#define WMMA_F32 0x1u

typedef struct {
    shim_u64 mSize;
    shim_u64 nSize;
    shim_u64 kSize;
    shim_i32 aType;
    shim_i32 bType;
    shim_i32 cType;
    shim_i32 resultType;
    unsigned char saturatingAccumulation;
    unsigned char pad[7];
} shim_wmma_props;

typedef struct {
    const void *vtbl;
} shim_object;

/* ------------------------------------------------------------------ */
/* tiny freestanding helpers (no CRT imports)                          */
/* ------------------------------------------------------------------ */
static int guid_equal(const shim_guid *a, const void *b)
{
    const unsigned char *p = (const unsigned char *)b;
    const unsigned char *q = (const unsigned char *)a;
    int i;
    for (i = 0; i < 16; i++)
        if (p[i] != q[i])
            return 0;
    return 1;
}

static shim_u32 str_len(const char *s)
{
    shim_u32 n = 0;
    while (s[n])
        n++;
    return n;
}

typedef struct {
    char buf[640];
    shim_u32 len;
} shim_line;

static void line_init(shim_line *l)
{
    l->len = 0;
    l->buf[0] = 0;
}

static void line_str(shim_line *l, const char *s)
{
    while (*s && l->len < sizeof(l->buf) - 1)
        l->buf[l->len++] = *s++;
    l->buf[l->len] = 0;
}

static void line_hex(shim_line *l, shim_u64 v, int digits)
{
    static const char hex[] = "0123456789ABCDEF";
    char tmp[17];
    int i;
    if (digits < 1)
        digits = 1;
    if (digits > 16)
        digits = 16;
    for (i = 0; i < digits; i++)
        tmp[i] = hex[(v >> (4 * (digits - 1 - i))) & 0xF];
    tmp[digits] = 0;
    line_str(l, tmp);
}

static void line_dec(shim_line *l, shim_u64 v)
{
    char tmp[21];
    int i = 20;
    tmp[i] = 0;
    if (v == 0) {
        line_str(l, "0");
        return;
    }
    while (v && i > 0) {
        tmp[--i] = (char)('0' + (v % 10));
        v /= 10;
    }
    line_str(l, &tmp[i]);
}

static void line_guid(shim_line *l, const shim_guid *g)
{
    shim_u32 d2 = g->d2, d3 = g->d3;
    line_hex(l, g->d1, 8);
    line_str(l, "-");
    line_hex(l, d2, 4);
    line_str(l, "-");
    line_hex(l, d3, 4);
    line_str(l, "-");
    line_hex(l, ((shim_u64)g->d4[0] << 8) | g->d4[1], 4);
    line_str(l, "-");
    {
        int i;
        for (i = 2; i < 8; i++)
            line_hex(l, g->d4[i], 2);
    }
}

static const char *iid_name(const void *iid)
{
    if (guid_equal(&IID_Factory, iid))
        return "IAmdExtD3DFactory";
    if (guid_equal(&IID_Device8, iid))
        return "IAmdExtD3DDevice8";
    if (guid_equal(&IID_ShaderIntrinsics, iid))
        return "IAmdExtD3DShaderIntrinsics";
    if (guid_equal(&IID_FfxApi, iid))
        return "IAmdExtFfxApi";
    if (guid_equal(&IID_FlipMeter, iid))
        return "IAmdExtFlipMeter";
    return "unknown";
}

static void hr_str(shim_line *l, shim_i32 hr)
{
    if (hr == S_OK_) {
        line_str(l, "S_OK");
        return;
    }
    if (hr == E_NOINTERFACE_) {
        line_str(l, "E_NOINTERFACE");
        return;
    }
    if (hr == E_NOTIMPL_) {
        line_str(l, "E_NOTIMPL");
        return;
    }
    if (hr == E_POINTER_) {
        line_str(l, "E_POINTER");
        return;
    }
    line_str(l, "0x");
    line_hex(l, (shim_u32)hr, 8);
}

/* ------------------------------------------------------------------ */
/* logging (KERNEL32 only on Windows; stdio in the host twin)          */
/* ------------------------------------------------------------------ */
#if defined(AMDXC_HOST_TEST)

static int shim_enabled(void)
{
    const char *v = getenv("AMDXC_SHIM");
    return v && v[0] && !(v[0] == '0' && !v[1]);
}

static void write_log_line(const char *line, shim_u32 len)
{
    const char *path = getenv("AMDXC_SHIM_LOG");
    FILE *f;
    if (!path || !path[0])
        return;
    f = fopen(path, "ab");
    if (!f)
        return;
    fwrite(line, 1, len, f);
    fputc('\n', f);
    fclose(f);
}

#else

static int shim_enabled(void)
{
    WCHAR value[8];
    DWORD n = GetEnvironmentVariableW(L"AMDXC_SHIM", value, 8);
    if (n == 0 || n >= 8)
        return 0;
    return !(value[0] == L'0' && value[1] == 0);
}

static void write_log_line(const char *line, shim_u32 len)
{
    static WCHAR path[1024];
    DWORD n = GetEnvironmentVariableW(L"AMDXC_SHIM_LOG", path, 1024);
    HANDLE h;
    DWORD written;
    if (n == 0 || n >= 1024)
        return;
    h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                    NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    WriteFile(h, line, len, &written, NULL);
    CloseHandle(h);
}

#endif

static void log_call(const shim_line *l)
{
    if (!shim_enabled())
        return;
    write_log_line(l->buf, l->len);
}

static void log_begin(shim_line *l, const char *call)
{
    line_init(l);
    line_str(l, "call=");
    line_str(l, call);
}

static void log_end(shim_line *l, shim_i32 hr)
{
    line_str(l, " result=");
    hr_str(l, hr);
    log_call(l);
}

/* ------------------------------------------------------------------ */
/* objects                                                             */
/* ------------------------------------------------------------------ */
static shim_object g_factory;
static shim_object g_device8;
static shim_object g_intrinsics;
static shim_object g_ffx;

static shim_i32 SHIM_CALL obj_qi(shim_object *self, const void *iid, void **out)
{
    (void)self;
    (void)iid;
    if (out)
        *out = NULL;
    return E_NOINTERFACE_;
}

static shim_u32 SHIM_CALL obj_addref(shim_object *self)
{
    (void)self;
    return 1;
}

static shim_u32 SHIM_CALL obj_release(shim_object *self)
{
    (void)self;
    return 0; /* static singletons are never freed */
}

/* ---- Device8 ---- */
static shim_i32 SHIM_CALL device8_stub(shim_object *self)
{
    (void)self;
    return S_OK_;
}

static shim_i32 SHIM_CALL device8_get_wmma(shim_object *self, shim_u64 *count,
                                           shim_wmma_props *props)
{
    shim_line line;
    shim_u64 capacity;
    shim_u64 out_count = 0;

    (void)self;
    if (count == NULL) {
        log_begin(&line, "Device8::GetWaveMatrixProperties");
        line_str(&line, " count=NULL");
        log_end(&line, E_POINTER_);
        return E_POINTER_;
    }
    capacity = *count;
    if (props != NULL && capacity >= 1) {
        /* Write only the first entry and leave the rest of the caller's
         * array untouched. */
        props[0].mSize = 16;
        props[0].nSize = 16;
        props[0].kSize = 16;
        props[0].aType = WMMA_FP8;
        props[0].bType = WMMA_FP8;
        props[0].cType = WMMA_F32;
        props[0].resultType = WMMA_F32;
        props[0].saturatingAccumulation = 0;
        out_count = 1;
    }
    *count = out_count;

    log_begin(&line, "Device8::GetWaveMatrixProperties");
    line_str(&line, " count_in=");
    line_dec(&line, capacity);
    line_str(&line, " count_out=");
    line_dec(&line, out_count);
    if (out_count) {
        line_str(&line, " m=16 n=16 k=16 a=0xB b=0xB c=0x1 r=0x1 sat=0");
    }
    log_end(&line, S_OK_);
    return S_OK_;
}

/* ---- ShaderIntrinsics ---- */
static shim_i32 SHIM_CALL si_get_info(shim_object *self, void *info)
{
    shim_line line;
    (void)self;
    (void)info;
    log_begin(&line, "SI::GetInfo");
    log_end(&line, S_OK_);
    return S_OK_;
}

static shim_i32 SHIM_CALL si_check_support(shim_object *self, shim_i32 intrinsic)
{
    shim_line line;
    (void)self;
    log_begin(&line, "SI::CheckSupport intrinsic=0x");
    line_hex(&line, (shim_u32)intrinsic, 4);
    log_end(&line, S_OK_);
    return S_OK_;
}

static shim_i32 SHIM_CALL si_enable(shim_object *self)
{
    shim_line line;
    (void)self;
    log_begin(&line, "SI::Enable");
    log_end(&line, S_OK_);
    return S_OK_;
}

/* ---- FfxApi ---- */
static shim_i32 SHIM_CALL ffx_update_provider(shim_object *self, const void *data,
                                              shim_u32 size)
{
    shim_line line;
    (void)self;
    log_begin(&line, "FfxApi::UpdateFfxApiProvider");
    line_str(&line, " size=");
    line_dec(&line, size);
    if (data != NULL && size >= 12) {
        const shim_u32 *d = (const shim_u32 *)data;
        line_str(&line, " version=");
        line_dec(&line, d[0]);
        line_str(&line, " descType=0x");
        line_hex(&line, d[2] | ((shim_u64)d[3] << 32), 16);
    }
    log_end(&line, E_NOINTERFACE_);
    return E_NOINTERFACE_;
}

/* ---- factory ---- */
static shim_i32 SHIM_CALL factory_create_interface(shim_object *self,
                                                   void *outer, const void *iid,
                                                   void **out)
{
    shim_line line;
    shim_i32 hr = E_NOINTERFACE_;
    (void)self;
    (void)outer;
    if (out == NULL)
        return E_POINTER_;

    if (guid_equal(&IID_Device8, iid)) {
        *out = &g_device8;
        hr = S_OK_;
    } else if (guid_equal(&IID_ShaderIntrinsics, iid)) {
        *out = &g_intrinsics;
        hr = S_OK_;
    } else {
        *out = NULL;
    }

    log_begin(&line, "Factory::CreateInterface iid=");
    line_guid(&line, (const shim_guid *)iid);
    line_str(&line, " (");
    line_str(&line, iid_name(iid));
    line_str(&line, ")");
    log_end(&line, hr);
    return hr;
}

/* vtable layouts: IUnknown + interface methods, exact slot counts. */
static const void *const factory_vtable[4] = {
    (const void *)obj_qi,
    (const void *)obj_addref,
    (const void *)obj_release,
    (const void *)factory_create_interface,
};
static const void *const device8_vtable[17] = {
    (const void *)obj_qi,
    (const void *)obj_addref,
    (const void *)obj_release,
    (const void *)device8_stub, /* unknown1 */
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub,
    (const void *)device8_stub, /* unknown13 */
    (const void *)device8_get_wmma,
};
static const void *const intrinsics_vtable[6] = {
    (const void *)obj_qi,
    (const void *)obj_addref,
    (const void *)obj_release,
    (const void *)si_get_info,
    (const void *)si_check_support,
    (const void *)si_enable,
};
static const void *const ffx_vtable[4] = {
    (const void *)obj_qi,
    (const void *)obj_addref,
    (const void *)obj_release,
    (const void *)ffx_update_provider,
};

static shim_object g_factory = {factory_vtable};
static shim_object g_device8 = {device8_vtable};
static shim_object g_intrinsics = {intrinsics_vtable};
static shim_object g_ffx = {ffx_vtable};

/* ------------------------------------------------------------------ */
/* export: AmdExtD3DCreateInterface                                    */
/* ------------------------------------------------------------------ */
SHIM_EXPORT shim_i32 SHIM_CALL AmdExtD3DCreateInterface(void *outer,
                                                        const void *iid,
                                                        void **out)
{
    shim_line line;
    shim_i32 hr = E_NOINTERFACE_;

    if (out == NULL)
        return E_POINTER_;
    *out = NULL;

    if (!shim_enabled()) {
        return E_NOINTERFACE_; /* inert unless explicitly enabled */
    }

    if (guid_equal(&IID_Factory, iid)) {
        *out = &g_factory;
        hr = S_OK_;
    } else if (guid_equal(&IID_FfxApi, iid)) {
        *out = &g_ffx;
        hr = S_OK_;
    }

    (void)outer;
    log_begin(&line, "AmdExtD3DCreateInterface iid=");
    line_guid(&line, (const shim_guid *)iid);
    line_str(&line, " (");
    line_str(&line, iid_name(iid));
    line_str(&line, ")");
    log_end(&line, hr);
    return hr;
}

/* Optional drop-in exports of Proton's wine stub. None is used by the ML
 * gate; they exist so the shim can replace that DLL without breaking other
 * consumers in the same prefix. */
SHIM_EXPORT void *SHIM_CALL AmdGetDxcModuleHandle(void)
{
    return NULL;
}

SHIM_EXPORT shim_i32 SHIM_CALL GetSettingsBlobsAll(void)
{
    return E_NOTIMPL_;
}

SHIM_EXPORT shim_i32 SHIM_CALL OpenAdapter12(void)
{
    return E_NOTIMPL_;
}

SHIM_EXPORT shim_i32 SHIM_CALL OpenShimInterface(void)
{
    return E_NOTIMPL_;
}

#if !defined(AMDXC_HOST_TEST)
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(inst);
    return TRUE;
}
#endif
'''


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if proc.returncode != 0:
        print(proc.stdout[-4000:])
        print(proc.stderr[-4000:], file=sys.stderr)
        raise RuntimeError(f"command failed ({proc.returncode}): {cmd[0]}")
    return proc


def check_inputs():
    if not CLANG.is_file():
        raise RuntimeError(f"LLVM-MinGW clang not found: {CLANG}")
    for tool in (READOBJ, OBJDUMP):
        if not tool.is_file():
            raise RuntimeError(f"LLVM-MinGW tool not found: {tool}")
    if not str(BUILD_DIR.resolve()).startswith(str(ROOT.resolve())):
        raise RuntimeError("build dir escapes repo")


def write_sources() -> dict:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    src = SRC_DIR / "amdxc64_shim.c"
    deffile = SRC_DIR / "amdxc64.def"
    src.write_text(AMDXC64_SHIM_C)
    deffile.write_text(AMDXC64_DEF)
    return {"amdxc64_shim.c": sha256_file(src),
            "amdxc64.def": sha256_file(deffile)}


def parse_exports(path: Path) -> dict:
    proc = run([str(READOBJ), "--coff-exports", str(path)])
    exports = {}
    cur_ord = cur_name = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        m = re.match(r"Ordinal:\s*(\d+)", line)
        if m:
            cur_ord = int(m.group(1))
            continue
        m = re.match(r"Name:\s*(.*)", line)
        if m:
            cur_name = m.group(1).strip()
            continue
        if re.match(r"RVA:\s*(0x[0-9a-fA-F]+|\d+)", line) and cur_ord is not None:
            if cur_name:
                exports[cur_name] = cur_ord
            cur_ord = cur_name = None
    return exports


def parse_imports(path: Path) -> dict:
    proc = run([str(OBJDUMP), "-p", str(path)])
    text = proc.stdout.split("Export Table:")[0]
    imports = {}
    cur_dll = None
    for line in text.splitlines():
        m = re.match(r"\s*DLL Name:\s*(\S+)", line)
        if m:
            cur_dll = m.group(1)
            imports[cur_dll] = []
            continue
        m = re.match(r"\s*\d+\s+(?:0x[0-9a-fA-F]+\s+)?(\S+)", line)
        if m and cur_dll is not None and "Hint/Ord" not in line:
            imports[cur_dll].append(m.group(1))
    return imports


def verify_dll(dll: Path) -> dict:
    proc = run([str(OBJDUMP), "-f", str(dll)])
    if "pe-x86-64" not in proc.stdout:
        raise RuntimeError("amdxc64.dll is not PE32+ x86-64")
    exports = parse_exports(dll)
    if set(exports) != set(EXPECTED_EXPORTS):
        raise RuntimeError(f"export table mismatch: {sorted(exports)}")
    imports = parse_imports(dll)
    unknown = set(imports) - ALLOWED_IMPORT_DLLS
    if unknown:
        raise RuntimeError(f"unexpected DLL imports: {sorted(unknown)}")
    flat = [s for syms in imports.values() for s in syms]
    if "kernel32" not in " ".join(imports).lower():
        raise RuntimeError("KERNEL32 import missing")
    for sym in ("GetEnvironmentVariableW", "CreateFileW", "WriteFile",
                "CloseHandle"):
        if sym not in flat:
            raise RuntimeError(f"logging import missing: {sym}")
    data = dll.read_bytes()
    missing = []
    for s in EXPECTED_STRINGS:
        wide = b"".join(bytes((c, 0)) for c in s)
        if s not in data and wide not in data:
            missing.append(s.decode())
    if missing:
        raise RuntimeError(f"expected strings missing: {missing}")
    return {"exports": exports, "imports": imports}


def build_windows(commands: list) -> Path:
    OBJ_DIR.mkdir(parents=True, exist_ok=True)
    dll = BUILD_DIR / "amdxc64.dll"
    obj = OBJ_DIR / "amdxc64_shim.o"
    cflags = ["-O2", "-DNDEBUG", "-ffreestanding", "-fno-stack-protector",
              "-fno-builtin", "-Wall", "-Wextra"]
    run([str(CLANG), "-c", str(SRC_DIR / "amdxc64_shim.c"), "-o", str(obj)]
        + cflags)
    commands.append(["<clang>", "-c", "src/amdxc64_shim.c", "-o", "obj/amdxc64_shim.o"]
                    + cflags)
    link = [str(CLANG), "-shared", "-nostdlib", "-o", str(dll), str(obj),
            str(SRC_DIR / "amdxc64.def"), "-lkernel32",
            "-Wl,--entry,DllMain", "-Wl,--no-insert-timestamp"]
    run(link)
    commands.append(["<clang>", "-shared", "-nostdlib", "-o", "amdxc64.dll",
                     "obj/amdxc64_shim.o", "src/amdxc64.def", "-lkernel32",
                     "-Wl,--entry,DllMain", "-Wl,--no-insert-timestamp"])
    return dll


def build_host_test(commands: list) -> Path:
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    so = TEST_DIR / "libamdxc64_shim_test.so"
    cc = shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        raise RuntimeError("no host C compiler (gcc/clang) for test library")
    cmd = [cc, "-O2", "-DNDEBUG", "-DAMDXC_HOST_TEST", "-fPIC", "-shared",
           "-o", str(so), str(SRC_DIR / "amdxc64_shim.c"), "-Wall", "-Wextra"]
    run(cmd)
    commands.append([cc, "-O2", "-DAMDXC_HOST_TEST", "-fPIC", "-shared",
                     "-o", "test/libamdxc64_shim_test.so",
                     "src/amdxc64_shim.c"])
    return so


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--windows-only", action="store_true")
    group.add_argument("--host-only", action="store_true")
    group.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    check_inputs()
    src_hashes = write_sources()
    commands: list = []
    info: dict = {}

    if args.verify_only:
        dll = BUILD_DIR / "amdxc64.dll"
        if not dll.is_file():
            raise RuntimeError("amdxc64.dll missing; build first")
        info["dll"] = verify_dll(dll)
    else:
        if not args.host_only:
            dll = build_windows(commands)
            info["dll"] = verify_dll(dll)
            info["dll"].update({
                "path": "build/amdxc64-shim/amdxc64.dll",
                "size": dll.stat().st_size,
                "sha256": sha256_file(dll),
                "machine": "PE32+ x86-64",
            })
        if not args.windows_only:
            so = build_host_test(commands)
            info["test_so"] = {
                "path": "build/amdxc64-shim/test/libamdxc64_shim_test.so",
                "size": so.stat().st_size,
                "sha256": sha256_file(so),
            }

    proc = run([str(CLANG), "--version"])
    report = {
        "artifact": "amdxc64-shim",
        "purpose": ("minimal IAmdExtD3DFactory / IAmdExtD3DDevice8 / "
                    "IAmdExtD3DShaderIntrinsics / IAmdExtFfxApi answer for the "
                    "FSR FG 4.0.1 ML gate probe"),
        "design": "analysis/fg-401-static/amdxc-gate.md",
        "built_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "toolchain": {"dir": str(TOOLCHAIN.relative_to(ROOT)),
                      "clang": proc.stdout.splitlines()[0] if proc.stdout else ""},
        "source": src_hashes,
        "expected_exports": EXPECTED_EXPORTS,
        "env": {"enable": "AMDXC_SHIM=1", "log": "AMDXC_SHIM_LOG=<path>"},
        "commands": [" ".join(str(c) for c in cmd) for cmd in commands],
        "method": ("embedded C source compiled with LLVM-MinGW; DLL imports "
                   "only KERNEL32; never executed, only statically inspected. "
                   "Host twin built from the same source for ctypes tests."),
        **info,
    }
    if not args.verify_only:
        (BUILD_DIR / "report.json").write_text(
            json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
