# FSR 4 on XMX status upstream (xess-xmx-linux)

Record of what the `xess-xmx-linux` repo found and decided about the FSR 4 XMX
path, cloned on 2026-11-13 to verify it.

## What happened

Upstream **already had FSR 4 on XMX working**. It was not an unresolved technical
problem: on 2026-11-02 the author dropped it as a project direction, in commit
`99445d8` ("Docs: FSR 4 on XMX is no longer developed").

Reasons for dropping it, in their words (`docs/games.md`, section
"FSR 4 on XMX (Upscaler Builds from the OptiScaler Discord)"):

1. No significant performance gain over XeSS on XMX.
2. More setup complexity.
3. Conflict with XeSS frame generation: the combination worked, but it needed
   image corrections for each game, exactly what the project avoids
   (OptiScaler is the one that adapts per game).

What they did test: a single build ("B Boost", FileVersion `4.0.2.1`) on a single
GPU (Arc B390) and two games. Manual setup, nothing automated. The doc was
archived for reference.

## What their docs already documented

Before the abandonment, `docs/games.md` described almost the whole recipe that
this repo had been rediscovering:

- The plugin goes as `amd_fidelityfx_upscaler_dx12.dll`; OptiScaler is not
  mandatory but can be used.
- `fsr-original.dll` comes from AMD FSR SDK 2.4.0 (FSR 4.1.2), and the plugin
  reads the weights from there. `install.sh` and `tools/get-ffx.sh` already
  downloaded it.
- Native Windows `cabinet.dll` + `WINEDLLOVERRIDES=cabinet=n,b`, because Wine
  does not implement the ordinals 40, 43 and 45 that the plugin uses to
  decompress its kernels.
- `FSR4_XMX_LITE=1` for the Lite model.
- The patch `0005-anv-cm-sampler-descriptor-table.patch` is mandatory:
  "older drivers without patch 0005 render corrupted images".

That last point matches what we saw here: the magenta noise in the first trace
was the old driver without `0005`, not a broken PRE ABI.

## Performance they measured

Arc B390, 1280x800 render, no frame generation:

| Upscaler | Cyberpunk 2077 (avg fps) | CONTROL Resonant (fps) |
|---|---|---|
| XeSS Ultra Quality (XMX) | 57.5 | — |
| FSR 4 on XMX, full model | 56.4 | 35 |
| FSR 4 on XMX, Lite | 58.2 / 58.1 | 36 |

FSR 4 kernels: 2.5 ms per frame (full) and 1.9 ms (Lite). That is, **Lite is
faster**, not equal. If the overlay shows the same time for both models, it is
worth checking whether Lite is really running.

## What this repo adds then

Not the minimal bridge, which upstream already had: the 4.0.2X path ("B Boost")
was already documented and working. What remains as our own work:

- The **4.1.2X INT8** path, which upstream did not test (they stayed at `4.0.2.1`).
- Verification that `fsr-original.dll` satisfies the weights contract
  (`tools/xmx412_weight_scan.c`), instead of assuming it.
- The method of comparing runs by native-code fingerprint
  (`tools/xmx_kernel_set.py`) to rule out a silent fallback.
- The CMK3 prototype for explicit mapping and its patch generator.

## Lesson for the announcement

Any message to nitec or to the thread must acknowledge that the FSR 4 XMX path
was already supported by `xess-xmx-linux`. Presenting it as a new bridge from
scratch would be inaccurate. What is new is the 4.1.2 INT8 path and the
kernel-level verification.
