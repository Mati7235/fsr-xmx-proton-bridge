# VK_AMD_anti_lag (Anti-Lag 2) on ANV — software port on top of `vk_frame_pacer`

Date: 2026-11-22. Base Mesa: 26.3.0 (checkout in
`/home/matias/xess-xmx/build-20261113/mesa-src/26.3.0/`, copied with `cp -a`
to `/home/matias/xess-xmx/mesa-antilag-26.3.0/` so the original is not touched).
Patch: `patches/0004-anv-anti-lag.patch`. Target GPU: Intel Arc B580 (Xe2,
`ver == 20`).

## What is reused

- `src/vulkan/runtime/vk_frame_pacer.{h,c}`: already exists in 26.3 and is
  driver-agnostic. It intercepts `QueueSubmit2`/`QueuePresentKHR` through the
  dispatch table, injects timestamp queries + timeline semaphores per queue,
  and exposes `vk_frame_pacer_init/finish/enable/disable/evaluate/calibrate/
  get_user_data`. It was not touched: the port only consumes it.
- `src/amd/vulkan/radv_anti_lag.c` (152 lines): logical reference. The port
  is the same state machine (frame-time EMA with alpha 0.5, absolute-deviation
  EMA with alpha 0.125, queuing delay discounted, recalibration every 8 s,
  `maxFPS` as the floor of the delay, sleep with
  `os_time_nanosleep_until`), renaming `radv_` → `anv_`.

## What was added (5 files, see the patch)

- `src/intel/vulkan/anv_anti_lag.{c,h}` (new): `anv_device_init_anti_lag`,
  `anv_device_finish_anti_lag`, `anv_AntiLagUpdateAMD`. The entrypoint is
  resolved by name only: the generated `anv_entrypoints.h` already declares
  `anv_AntiLagUpdateAMD` as weak (it comes from `src/vulkan/registry/vk.xml`),
  so defining the strong symbol is enough — same as RADV. There is no
  `anv_extensions.py` in 26.3: the extension and feature are generated from
  `vk.xml`.
- `src/intel/vulkan/anv_physical_device.c`:
  `.AMD_anti_lag = device->has_reg_timestamp` next to `.AMD_buffer_marker`,
  and `.antiLag = pdevice->has_reg_timestamp` at the end of `get_features`.
  The gate is the same one ANV uses for `KHR_calibrated_timestamps`: the pacer
  needs calibrated timestamps (`vk_frame_pacer_calibrate` +
  `vk_device_get_timestamp`).
- `src/intel/vulkan/anv_device.c`: init after `init_device_state` (queues and
  dispatch table ready, as `vk_frame_pacer_init` requires), only if
  `device->vk.enabled_features.antiLag`; error → `goto fail_meta_device`.
  Finish in `anv_DestroyDevice` (after TRTT, before destroying queues) and in the
  `fail_queues` path (no-op if the pacer was never initialized).
- `src/intel/vulkan/meson.build`: adds `anv_anti_lag.c/.h`.

## How it is built (exact commands)

The ninja regeneration needs the pyenv of the original build (the system
python does not have `mako`):

```sh
export PATH=/home/matias/xess-xmx/build-20261113/pyenv/bin:$PATH
cd /home/matias/xess-xmx/mesa-antilag-26.3.0
ninja -C build src/intel/vulkan/libvulkan_intel.so -j8
```

ICD to test without installing:

```sh
S=/tmp/opencode/antilag-scratch
cat > $S/intel_icd.json <<EOF
{
  "file_format_version": "1.0.0",
  "ICD": {
    "library_path": "/home/matias/xess-xmx/mesa-antilag-26.3.0/build/src/intel/vulkan/libvulkan_intel.so",
    "api_version": "1.4"
  }
}
EOF
VK_DRIVER_FILES=$S/intel_icd.json vulkaninfo --summary
VK_DRIVER_FILES=$S/intel_icd.json vulkaninfo | grep -i -e anti_lag -e antiLag
cc tools/antilag_probe.c -lvulkan -o $S/antilag_probe
VK_DRIVER_FILES=$S/intel_icd.json $S/antilag_probe | tee analysis/antilag2-probe.log
```

## Probe results

`analysis/antilag2-probe.log` (`tools/antilag_probe.c`, binary in
`/tmp/opencode/antilag-scratch/antilag_probe`):

```text
deviceName: Intel(R) Arc(tm) B580 Graphics (BMG G21)
driverVersion: 26.3.0
extension VK_AMD_anti_lag: present (spec 1)
feature antiLag: true
vkCreateDevice with VK_AMD_anti_lag: OK
vkAntiLagUpdateAMD: resolved
mode=ON maxFPS=30 frames=60: 1.976 s (32.9 ms/frame)
mode=OFF maxFPS=30 frames=60: 0.000 s (0.0 ms/frame)
RESULT: PASS (expected ON ~= 2 s pacing, OFF << 1 s)
```

## Verification

`S=/tmp/opencode/antilag-scratch` (ICD with an absolute `library_path` to the
freshly built `.so`).

| Command | Expected output | Output obtained |
|---|---|---|
| `VK_DRIVER_FILES=$S/intel_icd.json vulkaninfo --summary` | `deviceName = Intel(R) Arc(TM) B580 Graphics`, Mesa driver 26.3.0 | `deviceName = Intel(R) Arc(tm) B580 Graphics (BMG G21)`, `driverVersion = 26.3.0` ✅ |
| `vulkaninfo \| grep -i -e anti_lag -e antiLag` | `VK_AMD_anti_lag` + `antiLag` | Only `VK_AMD_anti_lag : extension revision 1` ⚠️ (see note) |
| probe `mode=ON maxFPS=30` 60 frames | ≈ 2 s of pacing | `1.976 s (32.9 ms/frame)` ✅ |
| probe `mode=OFF` 60 frames | << 1 s | `0.000 s` ✅ |

Note: the `antiLag` feature **is** exposed and works (the probe reads it with
`vkGetPhysicalDeviceFeatures2`, creates the device with it and uses the
entrypoint), but this system `vulkaninfo` does not print it: its feature chain
is fixed and does not include `VkPhysicalDeviceAntiLagFeaturesAMD` (just as it
does not print `bufferMarker` from `VK_AMD_buffer_marker`). A limitation of the
client, not of the driver.

## Bugs found during verification

1. **Segfault in `vk_frame_pacer_enable`**: `vk_device_get_timestamp(..,
   VK_TIME_DOMAIN_DEVICE_KHR, ..)` llama `device->get_timestamp`, a hook that
   RADV sets in `radv_CreateDevice` but ANV left as NULL. Fix in
   `anv_anti_lag.c`: `anv_device_get_timestamp` via
   `intel_gem_read_render_timestamp` (the same ioctl used by
   `anv_GetCalibratedTimestampsKHR`), installed in
   `anv_device_init_anti_lag`, only when Anti-Lag is enabled.
2. **The copied `build/` pointed to the original source** (`Source dir:
   .../build-20261113/mesa-src/26.3.0`): el primer `.so` was compiled without the
   port. `build/` was deleted and reconfigured with `meson setup` + the exact
   options from the original `meson-log.txt`, adding to the environment
   `PKG_CONFIG_PATH=.../build-20261113/local-deps/lib/pkgconfig` and
   `local-deps/bin` (the prebuilt `SPIRV-LLVM-Translator`; `meson setup`
   fails without it with `Dependency "LLVMSPIRVLib" not found`). Read-only use
   of the `build-20261113` tree; the original was not modified.

## XeLL off switch

`IGDEXT_XELL_CAP=off` (environment variable, no OptiScaler.ini key involved).
It is read in `StartXellHook`
(`upstream/xess-xmx-linux/shim/src/dll/XellHook.cpp`): `off` (or `0`) sets
`g_capAuto = false` with no fixed cap → the shim does not hold frames in
`xellSleep` and the swap chain answers the game. Documented in
`upstream/xess-xmx-linux/docs/launch-options.md` (`IGDEXT_XELL_CAP=off`:
"Turns the low latency off"). Variants: `auto[:ms]` (margin), number
`1..1000000` (fixed cap in µs instead of pacing), `IGDEXT_XELL_CHECK=0` and
`IGDEXT_XELL_POLLS=0` (diagnostics only).

## Known risks

- **Double pacing**: Anti-Lag 2 (driver/Vulkan) and XeLL (shim, `xellSleep`)
  both put the game thread to sleep with different criteria. To measure pure
  Anti-Lag, disable XeLL with `IGDEXT_XELL_CAP=off`.
- **AMD extension on an Intel driver**: it is only a name; the implementation is
  100 % generic (`vk_frame_pacer`). The app must request `VK_AMD_anti_lag`
  explicitly; nothing changes if it is not requested.
- **`assert(timestampValidBits == 64)`** in `vk_frame_pacer_enable`
  (`vk_frame_pacer.c`): ANV reports 64 bits only for `ver >= 20`
  (`anv_physical_device.c`, Bspec 60411; pre-Xe2 are 36). On older Intel GPUs,
  calling with `mode = ON` aborts in debug builds. The
  `has_reg_timestamp` gate does not cover that: documented, not "fixed".
- **`vk_frame_pacer` patches the dispatch table** (`QueueSubmit2`/
  `QueuePresentKHR`) from `vk_frame_pacer_init` until `finish`: `finish`
  must run before `vk_device_finish` (this holds).

## What is still needed to test it in a D3D12 game (vkd3d-proton ≥ 3.0)

1. Install or expose the built ICD to the test prefix (disposable) and confirm
   `vulkaninfo` inside that environment.
2. A game with native Anti-Lag 2 (in-game menu) or vkd3d-proton ≥ 3.0 with
   `VK_AMD_anti_lag` support (see `upstream/vkd3d-proton`, the version pinned
   in this repo).
3. Compare latency/frame rate with XeLL off (`IGDEXT_XELL_CAP=off`) versus
   Anti-Lag ON, and then both combined; check `igdext_xell.log`
   (`XESS_LOG=1`) for the real frame rate.
4. Real validation = injection evidence + deterministic GPU readback (an
   overlay label or `S_OK` alone do not count, per AGENTS.md).
