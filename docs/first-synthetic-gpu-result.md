# First synthetic GPU result — 2026-10-23

**Positive result of the synthetic DPAS/resource-map probe on B580. It is not
validation of FSR, of the real PRE kernel, nor of Proton/OptiScaler/Cyberpunk.**

The user manually ran `build/lab-test-v02/run-manual.py --run-gpu` and reported
device `8086:e20b`, the harness success output and exit code 0.
The local evidence is in:

`build/lab-test-v02/runs/20261023-000311-6a2d4eeb/evidence/`

The later review was read-only and CPU checks only: the GPU was not run again.
The current hashes of the artifacts match the preparation manifest; the launcher
checks those hashes before invoking the harness.

## Evidence reviewed

- `anv_canary`: the adapted ANV recognized the control placeholder.
- `canary-evidence.txt`: correct marker and all other words intact.
- `probe-driver.log`: DIRECT layout (type 2), set 0/binding 0, offset 0,
  stride 64; injection of the CMK of 12,160 bytes, 128 GRF and CM LWS `(1,1,1)`.
- The log records the mapping `7 8 0 1 2 3 4 5 6 9 10`, dispatch of one group and
  one thread. It is not a direct reading of GPU registers or of their mask.
- `probe-readback.txt`: the harness checked 128 float32 for each of the eleven
  resources (**1,408 values**), each argument `i` with result `16+i`.
  Slots 11–15 remained intact.

The kernel previously compiled and audited contains native DPAS. The combination
of artifact identity, injection evidence and deterministic results is stronger
than `S_OK`, a marker or a created pipeline. The empty logs `icd-driver.log` and
`canary-driver.log` are not used as proof; the marker and the canary report do
exist. `icd-selection.txt` records the requested selection, not an independent
inspection of all loaded modules.

## Report identity

| File | SHA-256 |
|---|---|
| `probe-driver.log` | `8addac924fad97372113c101edd246bc1511547b06bd5ac25e2b6939434e30d6` |
| `probe-readback.txt` | `b795e00ed04ad4f031c1473340c66843bd896401501f9cba7c906aed891fa1e1` |

Full local inventory: `analysis/first-gpu-evidence-review.json`. The reports
contain the harness checks, not an independent binary dump of the buffers. The driver
and other binary artifacts are not redistributed.

## What remains untested

It is a positive run of a custom kernel with storage buffers and explicit heap.
It does not demonstrate repeatability between runs, image or sampler support for
the PRE, compatibility of the VKD3D mutable heap, nor the complete FSR stages. The
next milestone is to design a micro-test with images/sampler and controlled inputs
for the real PRE, with a correctness criterion before running it.
There is no implicit authorization for new GPU experiments or for touching games.
