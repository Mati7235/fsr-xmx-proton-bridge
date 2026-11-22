# Roadmap

What is closed, what is worth a first check, and what stays out of scope.

## Closed

### Anti-Lag 2 on ANV

The port of `VK_AMD_anti_lag` over `vk_frame_pacer` worked. A probe paced 60 frames to
1.976 s at a 30 FPS floor. The work showed that the pacer only needs calibrated
timestamps, and ANV had to install a `get_timestamp` hook. The line stopped because
OptiScaler already offers low-latency options (XeLL in the shim, LatencyFlex), so a Mesa
patch that duplicated them no longer paid for itself. Reopening needs a game that asks
for `VK_AMD_anti_lag` by name and cannot use XeLL or LatencyFlex.

### FSR frame generation

FSR 4 frame generation needs the AGS WMMA path. vkd3d-proton does not expose it, and Intel
Xe2 cannot express a 16x16x16 matrix operation, so the network does not build on this
stack. The ML network is 191 passes in a strict sequential chain, and no partial port
produces a usable frame. A hand port is estimated at 620 to 1350 hours. The Windows 11
prefix gate was solved and the runtime does pick FSR 4.1.2, but every skipped ML pass
means a duplicated frame. AMD's frame pacing fix (Adrenalin 26.10.1, FSR SDK 2.4) depends
on RDNA4 hardware flip metering and the Windows driver, so there is no Linux path. The
cheap reopen, 8 to 16 hours, is to check whether Mesa or ANV could advertise a 16x16x16
cooperative matrix and lower it to two 8x16x16 operations.

## To investigate

### AMD neural radiance caching

Radiance caching stores indirect lighting in a world-space cache and reuses it between
frames, so global illumination needs fewer rays. It matters here because it improves
image quality without the frame pacing that only AMD hardware provides. Nothing shows it
runs on Intel. The first cheap check is a static scan of the FidelityFX Radiance Caching
library for AGS WMMA or 16x16x16 cooperative matrix use, before any port.

### AMD ray regeneration

Ray regeneration rebuilds a full-resolution image from sparse ray samples, using a small
neural network in the AMD FidelityFX implementation. It is interesting for the same
reason, since better reconstruction does not depend on pacing hardware. It is unverified
on Intel. The first cheap check is the pass inventory and WMMA census that closed FSR
frame generation early.

## Not planned

Upscaling and model work stays as documented in
[xmx412-model-selection.md](xmx412-model-selection.md).
