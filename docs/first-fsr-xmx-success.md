# First functional FSR 4 on XMX on Linux (2026-11-13)

**Functional result in the game, not just injection.** Marvel's Spider-Man Remastered
renders the scene correctly with the XMX 4.1.2 mod, the shim and a custom ANV driver, on an
Intel Arc B580. The UI and the 3D world are coherent; the upscaler reports ~0.99 ms.

It is still not a bit-exact validation of FSR: there is no independent oracle nor a
deterministic readback of the PRE. It is the project's first correct visual/functional
result.

## Exact setup

- Candidate package `xess-xmx-linux-20261113-cmk3` (side-by-side, not installed on the
  system): Mesa 26.3.0 + series of the `662dc6e` fork + shim 861,184 B.
- Driver used only per process: `VK_DRIVER_FILES` pointing to the candidate's ICD,
  new `ANV_CM_HELPER`, `VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer`,
  `ANV_CM_DEBUG=1`, `WINEDLLOVERRIDES="cabinet=n,b"`.
- Disposable prefix of the trace run (the user's saves copied), Proton Experimental, mod
  `fadbcb50…`, OptiScaler `Dx12Upscaler = ffx`.
- Command: `runs/20261112-161210-c1561db6/run-candidate.sh`.

## Evidence

| Artifact | Value |
|---|---|
| Log | `evidence/vkd3d-trace3-20261113.log`, 19,523 lines |
| SHA-256 | `012ac930a7369d9723234b4e84a9d68aaa6dba7e1827bd72578da3d368c1d957` |
| PRE | `~/.cache/xess-xmx/kernels/e8fca351200197b3_e20b_142835e7.cmk` (CMK2, 30,936 B) |
| Key line | `ANV CM: …e8fca351200197b3_e20b_142835e7.cmk: sampler descriptor table after the surfaces (sampler heap found)` |
| FSR4 resources detected | 11 `FSR4 resource detected` lines |
| Device lost | 0 |

The PRE was compiled with the new helper (gen `142835e7`, different from `0913d3f4` of
the old package) and the new driver applied the table sampler path:
`table_pc_base = push_size - 4*(nsurf+1) = 52 - 48 = 4` and
`cm_sampler_pc_off = 48`.

## What closed the problem

1. The CMK magic was inverted in the inherited 0001 patch: the driver would have rejected
   all kernels. Fixed and covered by a semantic test.
2. The installed package was old (`0913d3f4`) and lacked the fork's table-sampler support
   (`0005`), which is what fixes the base offset mismatch (8 → 4) and the sampler offset.
   The earlier trace with magenta noise was consistent with that driver, not with a broken
   PRE ABI.
3. The 4.1.2 mod packs need `Cabinet.dll` (LZMS Compression API), which Wine does not
   implement; the game-local shim provides it.

## What it does not prove

- Mathematical exactness of FSR nor equivalence with the reference implementation (no
  oracle).
- Real formats/contents of the 8 images (no RenderDoc capture).
- That the package works system-wide or in other games/prefixes.
- Repeatability across runs (a single session).

## Next

System-wide installation of the candidate package (user decision; rollback in
`backup-20261113`), and then a RenderDoc capture for formats + oracle.
