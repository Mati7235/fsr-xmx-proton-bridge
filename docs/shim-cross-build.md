# Cross-compilation of the shim, without execution

The full shim was compiled from Linux for Windows x86-64. This checks
compilation/linking, **not** that Wine/Proton loads the DLL or that FSR works.
The toolchain was not installed, the DLL was not run and no prefix was altered.

## Provenance

- Upstream: `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3` (re-validation
  2026-11-13); the historical baseline of this document was taken on
  `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- Toolchain: LLVM-MinGW `20261020`, UCRT, Ubuntu 22.04 x86-64, Clang 23.1.4.
- Local original file:
  `artifacts/original/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64.tar.xz`.
- SHA-256 checked against the digest of the GitHub release:
  `55064b60b991a1e1e8090b8c2f84e82b22cfe5903d12c159d65064cf5e8ae335`.
- Release: <https://github.com/mstorsjo/llvm-mingw/releases/tag/20261020>.
- Local extraction with `tarfile`, `data` filter, inside
  `artifacts/extracted/llvm-mingw-20261020-ucrt/`.

The original file stays immutable. Toolchain, upstream sources and generated
DLLs are git-ignored; they are not redistributed here.

## Baseline and configuration

`upstream/xess-xmx-linux/shim/` was copied to
`build/shim-cross-baseline-v01/source/`, without modifying the upstream checkout.
The first build failed at `Trace.cpp:62`: `__try` not recognized.
Clang's Microsoft extensions were enabled with `-fms-extensions`;
the exception-handling block was neither removed nor replaced.

Configuration commands, once the source copy is prepared:

```sh
TC="$PWD/artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin"
cmake -S build/shim-cross-baseline-v01/source \
  -B build/shim-cross-baseline-v01/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build build/shim-cross-baseline-v01/obj -j 4
```

The 13 objects and the link finished correctly. Static inspection with
`llvm-readobj --file-headers --coff-imports` identifies a PE32+ AMD64 DLL.
The baseline DLL is 1,615,360 bytes and has SHA-256
`43dec833e340cc75ad36d29200e2c5958c6ded8beb1eca5753c7d94d40f92e01`.
That hash identifies this run: a bit-for-bit reproducible build is not declared.
The local report `build/shim-cross-baseline-v01/report.json` records the hashes of
sources, DLL and imports; `pe-inspection.txt` keeps the full inspection.

## Limits of this build

### Context-correction variant

The baseline was copied to `build/shim-cross-context-v01/source/` and
`patches/0002-shim-context-output.patch` was applied with `patch -p2` from that
copy. Only `src/dll/IgdextApiDll.cpp` changed. The configuration and build
above were repeated, replacing `shim-cross-baseline-v01` with `shim-cross-context-v01`.

The 13 objects and the link finished correctly. The patched DLL is 1,615,872
bytes and has SHA-256
`c5b5620f5b8dca1fa44ad853e30cae31a6541a779d896c90810802cc4afbde0d`.
The patch used has SHA-256
`fa9c302b4cc3cc9ac4fff746c41c17d94a06e879e37f50da60f116f3337d8508`.
The 75 exports (name and ordinal) and the list of imported DLLs match the
baseline. It is not claimed that the addresses or the whole PE are identical.
The report and inspection are in `build/shim-cross-context-v01/report.json`
and `pe-inspection.txt`. See [context correction and CPU tests](context-output-fix.md).

### Re-validation on 662dc6e (stack 0002→0003)

The isolated copy must include `common/`, because the new shim includes
`../../../common/lowlat_check.h`. `shim/` and `common/` were copied to
`/tmp/opencode/xmx662-shim-stack/tree/`, the new patches were applied with
`patch -p2` from `tree/shim`, and it was configured/built with the same LLVM-MinGW
`20261020` UCRT and `-fms-extensions`.

```sh
cp -a upstream/xess-xmx-linux/shim /tmp/opencode/xmx662-shim-stack/tree/shim
cp -a upstream/xess-xmx-linux/common /tmp/opencode/xmx662-shim-stack/tree/common
patch -p2 --batch --forward -d /tmp/opencode/xmx662-shim-stack/tree/shim \
  -i "$PWD/patches/0002-shim-context-output.patch"
patch -p2 --batch --forward -d /tmp/opencode/xmx662-shim-stack/tree/shim \
  -i "$PWD/patches/0003-shim-context-reuse.patch"
cmake -S /tmp/opencode/xmx662-shim-stack/tree/shim \
  -B /tmp/opencode/xmx662-shim-stack/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/opencode/xmx662-shim-stack/obj -j 4
```

Result: **14/14 objects + link, 0 errors, 0 warnings**. DLL
`igdext64.dll` of 861,184 bytes, SHA-256
`0a0b54623be219a7a809eb1b628ebfcc4583bff472c097500be840f69bca8cf8`,
PE32+ AMD64, **79 named exports**, imports `KERNEL32.dll`,
`ADVAPI32.dll` and the UCRT family `api-ms-win-crt-*`. The DLL is smaller than the
`ef39559` baseline because upstream removed the static kernel tables and
moved the CMK2 packaging to the driver. The patches used are 0002
(`fc00a77dd81b9efc6ef3bd61affaa594752c50ebbb27f5a95bad13d39f93f263`) and 0003
(`ef8112d46f70f6242de9509926a35e66c6fe417a50947adff86c5caf855f054c`).
The DLL was not run. The local report is in
`build/shim-cross-662dc6e/report.json` (git-ignored), together with the logs and
the PE inspection.

### Pending validation

The UCRT variant statically links the C++ runtime according to the upstream CMake, but
**keeps imports of the UCRT APIs**, in addition to KERNEL32 and ADVAPI32.
It is not equivalent to upstream's MSVC distribution with a fully static CRT.
The availability of those imports in any prefix was not checked.

There is no proof of loading, real context calls, GPU detection or injection
under Proton. Do not copy this artifact into a game as if it were validated; a
later runtime test requires authorization and a disposable environment.
