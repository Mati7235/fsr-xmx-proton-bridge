#!/usr/bin/env python3
"""Build the minimal game-local cabinet.dll substitute (CPU-only research).

Compiles the four wimlib LZMS decoder translation units from the local
upstream/wimlib checkout (read-only) plus an embedded wrapper
(cabinet_shim.c) with the local LLVM-MinGW toolchain into
build/cabinet-shim/cabinet.dll, exporting only MS Compression API ordinals
40 (CreateDecompressor), 43 (Decompress) and 45 (CloseDecompressor).

Also builds a host test library (same sources, same flags where possible)
at build/cabinet-shim/test/libcabinet_shim_test.so so tests can exercise
the exact decoder + container logic via ctypes without Wine.

Safety boundaries (fail closed on violation):
  * read-only wrt upstream/, artifacts/original, games, Steam, prefixes;
  * writes only under build/cabinet-shim/;
  * never executes the produced DLL/.so, Wine, or any game/mod binary;
  * only compile + link + static inspection (readobj/objdump).

Usage:
  python3 tools/build_cabinet_shim.py [--windows-only | --host-only |
                                       --verify-only]
"""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "cabinet-shim"
SRC_DIR = BUILD_DIR / "src"
OBJ_DIR = BUILD_DIR / "obj"
TEST_DIR = BUILD_DIR / "test"

TOOLCHAIN = (ROOT / "artifacts" / "extracted" / "llvm-mingw-20261020-ucrt" /
             "llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64")
CLANG = TOOLCHAIN / "bin" / "x86_64-w64-mingw32-clang"
READOBJ = TOOLCHAIN / "bin" / "llvm-readobj"
OBJDUMP = TOOLCHAIN / "bin" / "x86_64-w64-mingw32-objdump"

WIMLIB = ROOT / "upstream" / "wimlib"
WIMLIB_TUS = [
    "src/lzms_decompress.c",
    "src/lzms_common.c",
    "src/decompress_common.c",
    "src/compress_common.c",
]
WIMLIB_INCLUDE = WIMLIB / "include"

EXPECTED_EXPORTS = {
    40: "CreateDecompressor",
    43: "Decompress",
    45: "CloseDecompressor",
}
# Load-time dependencies the DLL is allowed to have. Anything else (notably
# FDI/FCI hosts, networking, or driver DLLs) fails the build.
ALLOWED_IMPORT_DLLS = {
    "KERNEL32.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
}

CABINET_DEF = """LIBRARY cabinet
EXPORTS
CreateDecompressor @40
Decompress @43
CloseDecompressor @45
"""

CABINET_SHIM_C = r'''/*
 * cabinet_shim.c - Minimal game-local Cabinet.dll substitute (research only).
 *
 * Exports the three MS Compression API entry points the XMX 4.1.2 loader
 * (FUN_180029640) imports by ordinal:
 *   ordinal 40 = CreateDecompressor
 *   ordinal 43 = Decompress
 *   ordinal 45 = CloseDecompressor  (MS SDK name; the loader task calls it
 *                                    "DestroyDecompressor" - same role:
 *                                    releases the decompressor handle)
 *
 * Scope: LZMS (COMPRESS_ALGORITHM_LZMS = 5) buffer-mode containers only,
 * i.e. the 24-byte header + chunk stream the six 4.1.2 packs use, plus an
 * auxiliary COMPRESS_RAW single-block path. Everything else (FDI/FCI,
 * compressors, XPRESS/MSZIP, Query/Reset/Set) is intentionally absent.
 *
 * The raw LZMS block decoder is wimlib's (Eric Biggers, LGPL-2.1+), compiled
 * from the local upstream/wimlib checkout (see tools/build_cabinet_shim.py);
 * only the four decoder translation units are used:
 *   lzms_decompress.c, lzms_common.c, decompress_common.c, compress_common.c
 * (the last only for make_canonical_huffman_code, needed by the decoder's
 * adaptive Huffman rebuild). No wimlib global init is required: this file
 * drives lzms_decompressor_ops directly.
 *
 * CPU-only. No Wine/GPU/driver/prefix interaction. The Windows DLL uses the
 * process heap (KERNEL32) plus the default MinGW CRT startup; the host test
 * build uses libc.
 */

#ifdef _WIN32
#  include <windows.h>
#  ifndef DECOMPRESSOR_HANDLE
typedef PVOID DECOMPRESSOR_HANDLE;
#  endif
#else
#  include <stddef.h>
#  include <stdint.h>
typedef uint32_t DWORD;
typedef size_t SIZE_T;
typedef int BOOL;
typedef void *PVOID;
typedef void *DECOMPRESSOR_HANDLE;
#  define WINAPI
#  define TRUE 1
#  define FALSE 0
static __thread DWORD tls_last_error = 0;
static void SetLastError(DWORD e) { tls_last_error = e; }
#endif

#include <stdint.h>
#include <stddef.h>

#include "wimlib/decompressor_ops.h"

/* Win32 error codes used (cited from MS docs / winerror.h). */
#ifndef ERROR_SUCCESS
#  define ERROR_SUCCESS 0
#endif
#ifndef ERROR_INVALID_PARAMETER
#  define ERROR_INVALID_PARAMETER 87
#endif
#ifndef ERROR_NOT_SUPPORTED
#  define ERROR_NOT_SUPPORTED 50
#endif
#ifndef ERROR_INSUFFICIENT_BUFFER
#  define ERROR_INSUFFICIENT_BUFFER 122
#endif
#ifndef ERROR_BAD_COMPRESSION_BUFFER
#  define ERROR_BAD_COMPRESSION_BUFFER 287
#endif
#ifndef ERROR_FUNCTION_FAILED
#  define ERROR_FUNCTION_FAILED 1627
#endif

/* From compressapi.h (mingw-w64): */
#define CABSHIM_ALG_LZMS 5u
#define CABSHIM_COMPRESS_RAW 0x20000000u
#define CABSHIM_MAGIC 0xC0E5510Au
#define CABSHIM_HEADER_SIZE 24u
#define CABSHIM_MAX_TOTAL (128u * 1024u * 1024u)
#define CABSHIM_MAX_BLOCK (64u * 1024u * 1024u)
#define CABSHIM_LZMS_CAP (64u * 1024u * 1024u)

/* Allocation-routine callback types (compressapi.h). */
typedef PVOID (WINAPI *CABSHIM_ALLOC)(PVOID ctx, SIZE_T size);
typedef void (WINAPI *CABSHIM_FREE)(PVOID ctx, PVOID mem);
typedef struct {
  CABSHIM_ALLOC Allocate;
  CABSHIM_FREE Free;
  PVOID UserContext;
} CABSHIM_ROUTINES;

/* ------------------------------------------------------------------ */
/* Internal heap (process heap on Windows, libc on host test build).   */
/* ------------------------------------------------------------------ */
#ifdef _WIN32
static void *shim_alloc(SIZE_T n) {
  return HeapAlloc(GetProcessHeap(), 0, n);
}
static void shim_free(void *p) {
  if (p)
    HeapFree(GetProcessHeap(), 0, p);
}
/* 16-byte aligned alloc (DECODE_TABLE_ALIGNMENT is 16). */
static void *shim_aligned_alloc(SIZE_T n) {
  /* over-allocate: alignment + slack + offset byte */
  unsigned char *raw =
      (unsigned char *)HeapAlloc(GetProcessHeap(), 0, n + 32u);
  if (!raw)
    return NULL;
  unsigned char *aligned =
      (unsigned char *)(((uintptr_t)(raw + 32u)) & ~(uintptr_t)15u);
  aligned[-1] = (unsigned char)(aligned - raw);
  return aligned;
}
static void shim_aligned_free(void *p) {
  if (p) {
    unsigned char *aligned = (unsigned char *)p;
    HeapFree(GetProcessHeap(), 0, aligned - aligned[-1]);
  }
}
#else
#include <stdlib.h>
static void *shim_alloc(SIZE_T n) { return malloc(n ? n : 1); }
static void shim_free(void *p) { free(p); }
static void *shim_aligned_alloc(SIZE_T n) {
  void *p = NULL;
  if (posix_memalign(&p, 16, n ? n : 1))
    return NULL;
  return p;
}
static void shim_aligned_free(void *p) { free(p); }
#endif

/* ------------------------------------------------------------------ */
/* Freestanding helpers (Windows): avoid UCRT string imports so the DLL */
/* leans on KERNEL32 + the CRT startup only. Host build uses libc.      */
/* ------------------------------------------------------------------ */
#ifdef _WIN32
void *memset(void *d, int c, SIZE_T n) {
  unsigned char *p = (unsigned char *)d;
  SIZE_T i;
  for (i = 0; i < n; i++)
    p[i] = (unsigned char)c;
  return d;
}
void *memcpy(void *d, const void *s, SIZE_T n) {
  unsigned char *p = (unsigned char *)d;
  const unsigned char *q = (const unsigned char *)s;
  SIZE_T i;
  for (i = 0; i < n; i++)
    p[i] = q[i];
  return d;
}
#endif

/* Custom allocator routing for wimlib stubs (TLS, set around create/free). */
static __thread const CABSHIM_ROUTINES *tls_routines = NULL;

/* Stubs satisfying wimlib internal headers (util.h). Note: only MALLOC /
 * FREE / ALIGNED_* are used by the four compiled TUs. */
void *wimlib_malloc(size_t size) {
  if (tls_routines && tls_routines->Allocate)
    return tls_routines->Allocate(tls_routines->UserContext, size);
  return shim_alloc(size);
}
void wimlib_free_memory(void *p) {
  if (!p)
    return;
  if (tls_routines && tls_routines->Free) {
    tls_routines->Free(tls_routines->UserContext, p);
    return;
  }
  shim_free(p);
}
void *wimlib_realloc(void *ptr, size_t size) {
  (void)ptr;
  (void)size;
  return NULL; /* unused by the decoder TUs */
}
void *wimlib_calloc(size_t nmemb, size_t size) {
  (void)nmemb;
  (void)size;
  return NULL; /* unused by the decoder TUs */
}
void *wimlib_aligned_malloc(size_t size, size_t alignment) {
  (void)alignment; /* DECODE_TABLE_ALIGNMENT is 16; shim gives 16 */
  if (tls_routines && tls_routines->Allocate) {
    /* custom allocator has no alignment guarantee; over-allocate + align */
    unsigned char *raw = (unsigned char *)tls_routines->Allocate(
        tls_routines->UserContext, size + 32u);
    if (!raw)
      return NULL;
    unsigned char *aligned =
        (unsigned char *)(((uintptr_t)(raw + 32u)) & ~(uintptr_t)15u);
    aligned[-1] = (unsigned char)(aligned - raw);
    return aligned;
  }
  return shim_aligned_alloc(size);
}
void wimlib_aligned_free(void *ptr) {
  if (!ptr)
    return;
  if (tls_routines && tls_routines->Free) {
    unsigned char *aligned = (unsigned char *)ptr;
    tls_routines->Free(tls_routines->UserContext, aligned - aligned[-1]);
    return;
  }
  shim_aligned_free(ptr);
}
/* cpu_features (cpu_features.h): force the portable x86-filter path.
 * The SSE4.2 path is an optimization only; results are bit-identical. */
unsigned int cpu_features = 0;

/* ------------------------------------------------------------------ */
/* Decompressor handle.                                                */
/* ------------------------------------------------------------------ */
#define CABSHIM_CTX_MAGIC 0x4341425348494D00ULL /* "CABSHIM\0" */

struct cabshim_ctx {
  uint64_t magic;
  uint32_t alg;
  int raw_mode;
  const CABSHIM_ROUTINES *routines; /* borrowed refs to callbacks only */
  CABSHIM_ROUTINES routines_copy;
  void *lzms_priv;
};

static uint32_t rd_u16le(const unsigned char *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8);
}
static uint32_t rd_u32le(const unsigned char *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
         ((uint32_t)p[3] << 24);
}

/* Bitwise CRC-32 (IEEE) update; header is 24 bytes so speed is irrelevant. */
static uint32_t crc32_update(uint32_t crc, const unsigned char *p, size_t n) {
  size_t i;
  crc ^= 0xFFFFFFFFu;
  for (i = 0; i < n; i++) {
    unsigned k;
    crc ^= p[i];
    for (k = 0; k < 8; k++)
      crc = (crc & 1u) ? (crc >> 1) ^ 0xEDB88320u : (crc >> 1);
  }
  return crc ^ 0xFFFFFFFFu;
}

/* ------------------------------------------------------------------ */
/* Exported API (MS prototypes from compressapi.h).                    */
/* ------------------------------------------------------------------ */
#ifdef _WIN32
#  define CABSHIM_API __declspec(dllexport)
#else
#  define CABSHIM_API __attribute__((visibility("default")))
#endif

CABSHIM_API BOOL WINAPI CreateDecompressor(DWORD Algorithm,
                                           const CABSHIM_ROUTINES *Routines,
                                           DECOMPRESSOR_HANDLE *Handle) {
  struct cabshim_ctx *ctx;
  uint32_t base_alg;
  if (Handle == NULL) {
    SetLastError(ERROR_INVALID_PARAMETER);
    return FALSE;
  }
  *Handle = NULL;
  base_alg = Algorithm & ~CABSHIM_COMPRESS_RAW;
  if (base_alg != CABSHIM_ALG_LZMS) {
    SetLastError(ERROR_NOT_SUPPORTED);
    return FALSE;
  }
  ctx = (struct cabshim_ctx *)shim_alloc(sizeof(*ctx));
  if (!ctx) {
    SetLastError(ERROR_FUNCTION_FAILED);
    return FALSE;
  }
  ctx->magic = CABSHIM_CTX_MAGIC;
  ctx->alg = Algorithm;
  ctx->raw_mode = (Algorithm & CABSHIM_COMPRESS_RAW) ? 1 : 0;
  ctx->lzms_priv = NULL;
  if (Routines && (Routines->Allocate || Routines->Free)) {
    if (!Routines->Allocate || !Routines->Free) {
      shim_free(ctx);
      SetLastError(ERROR_INVALID_PARAMETER);
      return FALSE;
    }
    ctx->routines_copy = *Routines;
    ctx->routines = &ctx->routines_copy;
  } else {
    ctx->routines = NULL;
  }
  tls_routines = ctx->routines;
  {
    int r = lzms_decompressor_ops.create_decompressor(CABSHIM_LZMS_CAP,
                                                      &ctx->lzms_priv);
    tls_routines = NULL;
    if (r != 0 || ctx->lzms_priv == NULL) {
      shim_free(ctx);
      SetLastError(ERROR_FUNCTION_FAILED);
      return FALSE;
    }
  }
  *Handle = (DECOMPRESSOR_HANDLE)ctx;
  SetLastError(ERROR_SUCCESS);
  return TRUE;
}

static BOOL check_ctx(const struct cabshim_ctx *ctx) {
  return ctx != NULL && ctx->magic == CABSHIM_CTX_MAGIC &&
         ctx->lzms_priv != NULL;
}

/* Decode one raw LZMS block. Returns 0 on success. */
static int raw_block(void *priv, const unsigned char *in, size_t in_len,
                     unsigned char *out, size_t out_len) {
  return lzms_decompressor_ops.decompress(in, in_len, out, out_len, priv);
}

CABSHIM_API BOOL WINAPI Decompress(DECOMPRESSOR_HANDLE Handle,
                                  PVOID InBuf, SIZE_T InSize, PVOID OutBuf,
                                  SIZE_T OutSize, SIZE_T *Produced) {
  struct cabshim_ctx *ctx = (struct cabshim_ctx *)Handle;
  const unsigned char *in;
  unsigned char *out;
  if (!check_ctx(ctx) || InBuf == NULL || OutBuf == NULL ||
      Produced == NULL) {
    SetLastError(ERROR_INVALID_PARAMETER);
    return FALSE;
  }
  *Produced = 0;
  if (InSize == 0 || OutSize == 0) {
    SetLastError(ERROR_INVALID_PARAMETER);
    return FALSE;
  }
  in = (const unsigned char *)InBuf;
  out = (unsigned char *)OutBuf;

  if (ctx->raw_mode) {
    /* Auxiliary path: whole input is one raw LZMS block. */
    if (raw_block(ctx->lzms_priv, in, InSize, out, OutSize) != 0) {
      SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
      return FALSE;
    }
    *Produced = OutSize;
    SetLastError(ERROR_SUCCESS);
    return TRUE;
  }

  /* Buffer mode: 24-byte container header + chunk stream. */
  {
    uint32_t header_size, total, blk, z1, z2;
    unsigned algo, hdr_crc;
    uint32_t crc;
    size_t pos = CABSHIM_HEADER_SIZE;
    size_t written = 0;
    if (InSize < CABSHIM_HEADER_SIZE ||
        rd_u32le(in) != CABSHIM_MAGIC) {
      SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
      return FALSE;
    }
    header_size = rd_u16le(in + 4);
    hdr_crc = in[6];
    algo = in[7];
    total = rd_u32le(in + 8);
    z1 = rd_u32le(in + 12);
    blk = rd_u32le(in + 16);
    z2 = rd_u32le(in + 20);
    if (header_size != CABSHIM_HEADER_SIZE || algo != CABSHIM_ALG_LZMS ||
        z1 != 0 || z2 != 0) {
      SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
      return FALSE;
    }
    crc = crc32_update(0, in, 6);
    crc = crc32_update(crc, in + 7, CABSHIM_HEADER_SIZE - 7);
    if ((crc & 0xFFu) != hdr_crc) {
      SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
      return FALSE;
    }
    if (total == 0 || total > CABSHIM_MAX_TOTAL || blk == 0 ||
        blk > CABSHIM_MAX_BLOCK) {
      SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
      return FALSE;
    }
    if (OutSize < total) {
      /* The loader requires the exact size; enforce no-short-buffer. */
      SetLastError(ERROR_INSUFFICIENT_BUFFER);
      return FALSE;
    }
    while (written < total) {
      uint32_t chunk_len;
      size_t want;
      if (pos + 4 > InSize) {
        SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
        return FALSE;
      }
      chunk_len = rd_u32le(in + pos);
      pos += 4;
      if (chunk_len == 0 || (size_t)chunk_len > InSize - pos) {
        SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
        return FALSE;
      }
      want = total - written;
      if (want > blk)
        want = blk;
      if ((size_t)chunk_len == want) {
        /* Stored verbatim. */
        size_t i;
        for (i = 0; i < want; i++)
          out[written + i] = in[pos + i];
      } else {
        if (raw_block(ctx->lzms_priv, in + pos, chunk_len, out + written,
                      want) != 0) {
          SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
          return FALSE;
        }
      }
      pos += chunk_len;
      written += want;
    }
    if (pos != InSize) {
      SetLastError(ERROR_BAD_COMPRESSION_BUFFER);
      return FALSE;
    }
    *Produced = total;
    SetLastError(ERROR_SUCCESS);
    return TRUE;
  }
}

CABSHIM_API void WINAPI CloseDecompressor(DECOMPRESSOR_HANDLE Handle) {
  struct cabshim_ctx *ctx = (struct cabshim_ctx *)Handle;
  if (!check_ctx(ctx)) {
    SetLastError(ERROR_INVALID_PARAMETER);
    return;
  }
  ctx->magic = 0;
  tls_routines = ctx->routines;
  if (ctx->lzms_priv)
    lzms_decompressor_ops.free_decompressor(ctx->lzms_priv);
  tls_routines = NULL;
  shim_free(ctx);
  SetLastError(ERROR_SUCCESS);
}

#ifdef _WIN32
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, PVOID reserved) {
  (void)inst;
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


def wimlib_revision() -> str:
    proc = subprocess.run(["git", "-C", str(WIMLIB), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("upstream/wimlib is not a git checkout")
    return proc.stdout.strip()


def clang_version() -> str:
    proc = run([str(CLANG), "--version"])
    return proc.stdout.splitlines()[0] if proc.stdout else ""


def check_inputs():
    if not CLANG.is_file():
        raise RuntimeError(f"LLVM-MinGW clang not found: {CLANG}")
    for tool in (READOBJ, OBJDUMP):
        if not tool.is_file():
            raise RuntimeError(f"LLVM-MinGW tool not found: {tool}")
    for rel in WIMLIB_TUS:
        if not (WIMLIB / rel).is_file():
            raise RuntimeError(f"wimlib TU missing (read-only dep): {rel}")
    if not (WIMLIB_INCLUDE / "wimlib" / "decompressor_ops.h").is_file():
        raise RuntimeError("wimlib headers missing under upstream/wimlib")


def write_sources() -> dict:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    wrapper = SRC_DIR / "cabinet_shim.c"
    deffile = SRC_DIR / "cabinet.def"
    wrapper.write_text(CABINET_SHIM_C)
    deffile.write_text(CABINET_DEF)
    return {
        "cabinet_shim.c": sha256_file(wrapper),
        "cabinet.def": sha256_file(deffile),
    }


def parse_coff_exports(path: Path) -> dict:
    proc = run([str(READOBJ), "--coff-exports", str(path)])
    exports = {}
    cur_ord = cur_name = cur_rva = None
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
        m = re.match(r"RVA:\s*(0x[0-9a-fA-F]+|\d+)", line)
        if m and cur_ord is not None:
            cur_rva = int(m.group(1), 16)
            if cur_name:
                exports[cur_ord] = {"name": cur_name, "rva": cur_rva}
            cur_ord = cur_name = cur_rva = None
    return exports


def parse_imports(path: Path) -> dict:
    proc = run([str(OBJDUMP), "-p", str(path)])
    # Only the import-table region: anything from "Export Table:" on is the
    # export directory, whose symbol lines must not leak into imports.
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


def build_windows(commands: list) -> Path:
    OBJ_DIR.mkdir(parents=True, exist_ok=True)
    dll = BUILD_DIR / "cabinet.dll"
    cflags = ["-O2", "-DNDEBUG", "-ffreestanding", "-Wall",
              f"-I{WIMLIB_INCLUDE}"]
    objs = []
    sources = [str(WIMLIB / rel) for rel in WIMLIB_TUS]
    sources.append(str(SRC_DIR / "cabinet_shim.c"))
    for src in sources:
        obj = OBJ_DIR / (Path(src).stem + ".o")
        cmd = [str(CLANG), "-c", src, "-o", str(obj)] + cflags
        run(cmd)
        commands.append(cmd)
        objs.append(str(obj))
    cmd = ([str(CLANG), "-shared", "-o", str(dll)] + objs +
           [str(SRC_DIR / "cabinet.def")])
    run(cmd)
    commands.append(cmd)
    return dll


def verify_dll(dll: Path) -> dict:
    proc = run([str(OBJDUMP), "-f", str(dll)])
    if "pe-x86-64" not in proc.stdout:
        raise RuntimeError("cabinet.dll is not PE32+ x86-64")
    exports = parse_coff_exports(dll)
    if exports != {o: {"name": n, "rva": exports[o]["rva"]}
                   for o, n in EXPECTED_EXPORTS.items()
                   if o in exports} or \
            {o: exports[o]["name"] for o in exports} != EXPECTED_EXPORTS:
        raise RuntimeError(f"export table mismatch: {exports}")
    imports = parse_imports(dll)
    unknown = set(imports) - ALLOWED_IMPORT_DLLS
    if unknown:
        raise RuntimeError(f"unexpected DLL imports: {sorted(unknown)}")
    return {"exports": {str(o): v for o, v in exports.items()},
            "imports": imports}


def build_host_test(commands: list) -> Path:
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    so = TEST_DIR / "libcabinet_shim_test.so"
    import shutil
    cc = shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        raise RuntimeError("no host C compiler (gcc/clang) for test library")
    sources = [str(WIMLIB / rel) for rel in WIMLIB_TUS]
    sources.append(str(SRC_DIR / "cabinet_shim.c"))
    cmd = ([cc, "-O2", "-DNDEBUG", "-fPIC", "-shared",
            "-fvisibility=hidden", "-o", str(so)] + sources +
           [f"-I{WIMLIB_INCLUDE}", "-Wall"])
    run(cmd)
    commands.append(cmd)
    return so


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--windows-only", action="store_true")
    group.add_argument("--host-only", action="store_true")
    group.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    check_inputs()
    for forbidden in ("artifacts/original", "upstream"):
        _ = forbidden  # documented read-only areas; never written below
    if not str(BUILD_DIR.resolve()).startswith(str(ROOT.resolve())):
        raise RuntimeError("build dir escapes repo")

    rev = wimlib_revision()
    tu_hashes = {rel: sha256_file(WIMLIB / rel) for rel in WIMLIB_TUS}
    src_hashes = write_sources()
    clang_ver = clang_version()
    commands: list = []
    info: dict = {}

    if args.verify_only:
        dll = BUILD_DIR / "cabinet.dll"
        if not dll.is_file():
            raise RuntimeError("cabinet.dll missing; build first")
        info["dll"] = verify_dll(dll)
    else:
        if not args.host_only:
            dll = build_windows(commands)
            info["dll"] = verify_dll(dll)
            info["dll"].update({
                "path": "build/cabinet-shim/cabinet.dll",
                "size": dll.stat().st_size,
                "sha256": sha256_file(dll),
            })
        if not args.windows_only:
            so = build_host_test(commands)
            info["test_so"] = {
                "path": "build/cabinet-shim/test/libcabinet_shim_test.so",
                "size": so.stat().st_size,
                "sha256": sha256_file(so),
            }

    report = {
        "artifact": "cabinet-shim",
        "built_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "toolchain": {"dir": str(TOOLCHAIN.relative_to(ROOT)),
                      "clang": clang_ver},
        "wimlib": {"rev": rev, "tus": tu_hashes},
        "wrapper": src_hashes,
        "expected_exports": {str(o): n
                             for o, n in EXPECTED_EXPORTS.items()},
        "commands": [" ".join(str(c) for c in cmd) for cmd in commands],
        "method": ("wimlib LZMS decoder TUs compiled in from the local "
                   "checkout (read-only); wrapper + .def embedded in this "
                   "script. No Wine/GPU/prefix use; binaries never "
                   "executed, only statically inspected."),
        **info,
    }
    if not args.verify_only:
        (BUILD_DIR / "report.json").write_text(
            json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
