# First lab test: preflight and limits

**Manual preparation is already finished:** see
[command, risks and expected results](manual-synthetic-test.md).
This document explains the inventory and its limits, not a GPU result.

This milestone prepares a reproducible inventory, not a launcher. The preflight reads
local files, extracts Meson metadata and computes SHA-256 of a bounded set of artifacts.
It does not invoke Mesa, the probe, `vulkaninfo`, Vulkan, the driver nor build tools; it
does not modify prefixes, Steam, the environment nor system files.

## Create the manifest

After building Mesa and generating the probe separately, run from the repository root,
changing paths if needed:

```sh
python tools/lab_preflight.py \
  --mesa-build build/mesa-26.1.2/out \
  --probe-dir build/lab-probe-v10 \
  --out analysis/lab-preflight.json
```

The JSON is written even if inputs are missing. Exit code `2` and status `blocked` mean
that evidence is missing or that the synthetic contract does not match; the block must
not be skipped. Code `0` only means that the required inventory is present and passes its
static checks. The status `inventory-complete-review-required` does **not** certify that
the Mesa build is correct nor that the driver was loaded. The manifest keeps paths, sizes
and hashes; it does not copy or package binaries.

It is an **inventory**, not a semantic validation of binaries: the preflight does not
disassemble nor interpret the content of Mesa, SPIR-V, CMK or zebin. It checks JSON
metadata and some declared values, requires CMK3 with an explicit heap, and compares the
zebin identity with the registered audit. It does not rerun that audit. It records hashes
to identify bytes. A textual search for `dpas.` in a disassembly file does not certify
the execution or correctness of DPAS either.

The local build produced an ANV `.so` and Meson metadata in `build/mesa-26.1.2/out`, but
mere presence does not prove the mask/dimensions, a correct patch, or a load test.
`build/lab-probe-v10` contains the probe with restricted audit and explicit heap; see
[evidence](lab-probe.md). Earlier outputs may be incomplete or use the incompatible
automatic heap. Do not reuse partial outputs as if they were a finished probe.

The probe identified by `kind` is a **synthetic DPAS/resource-map test**; it does not
contain the FSR kernel. `gpu_validated` must remain `false` until an independent GPU test.
Neither compilation, DPAS disassembly, PSO, `S_OK`, overlay nor preflight output is
evidence of injection or readback. The manifest explicitly marks
`fsr.complete_kernel_present=false`, `fsr.bridge_ready=false` and
`runtime_test_authorized=false`.

## Before any isolated manual test

There is no runtime-validated harness yet. `lab/bridge_probe.c` builds locally and
`lab/README.md` describes its controls and future invocation. Its CPU build does not
demonstrate injection nor GPU readback.
The inventory alone does not authorize a runtime test. To start the manual experiment,
use the reviewed preparation and the explicit opt-in described in
`manual-synthetic-test.md`, keeping these requirements:

1. The validation in `docs/lab-mesa-build.md` must confirm the Mesa patch and build, the
   execution mask and local dimensions; record the revision, relevant options and artifact
   hashes. The preflight does not deduce these facts from `libvulkan_intel.so`.
2. Complete and audit all probe deliverables. Keep the canary active; do not hide build
   errors or replace real DPAS with a constant.
3. Review the harness with known buffers, the check of the 11 results and of the intact
   slots, deterministic readback, and unambiguous evidence that the injected CM kernel was
   called. The probe is only an ABI control, not a full FSR.
4. For runtime, ask for explicit authorization. Use exclusively a new disposable prefix,
   never the Cyberpunk/Steam prefix; isolate environment variables in the test process, use
   only the local Mesa artifacts identified by hash, keep the canary and record logs/readback.
   Do not install drivers, change services or modify global configuration.
5. Stop on missing injection, readback discrepancy, build failure, canary failure or any
   difference from the expected values. Do not escalate to FSR nor to per-game integration
   until the failure is explained and the evidence reviewed.

The `build/lab-test-v02` preparation records the hashes of the harness/ICD/driver and
probe, and verifies their identity before each manual run. The agent did not run the GPU
test. The harness timeout does not guarantee recovering a hung GPU.
