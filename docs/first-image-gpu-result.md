# First GPU result for image/sampler — 2026-10-23

**Positive result of the synthetic image/sampler kernel on the B580.** The user manually
ran `build/image-test-v01/run-manual.py --run-gpu`; they reported PCI `8086:e20b`, the
harness checks passed, and exit code 0.

The later review only read the files of this run:

`build/image-test-v01/runs/20261023-005649-3b96a43b/evidence/`

No other GPU test was run. `tools/review_image_result.py` was used with the prepared
manifest: it verifies the current hashes, the canary, the injection/map log, and the binary
dump **independently of the C comparator**.

## Verified result

- The 64 sampled float32 values match the CPU reference: **maximum absolute error
  0.0**. It includes four channels, texel centers, central interpolation and out-of-edge
  coordinates with clamp-to-edge.
- The other **1,984 sentinel words** remain intact, including the tail of the output
  buffer and the unused buffers. The dump has the expected 8,192 bytes.
- Canary recognized; its report confirms the marker and the other words intact.
- Log: DIRECT heap (type 2), set 0/binding 0, offset 0/stride 64; sampler in the second
  set of the pipeline. Injection of **1,280 bytes**, 128 GRF, CM LWS `(1,1,1)`.
- Dispatch of selector `(2,1,5)` with indices `3 7`; walker with one group and one
  thread. These are driver logs, not a direct capture of hardware registers.

The hashes of the current files match the preparation. The pinned kernel contains native
`sample_lz`, an RGBA mask and the writing of the results; the CMK3 package enables the
sampler. Creating the pipeline alone or a successful exit code is not enough: here there is
evidence of injection and output bytes.

| Evidence | SHA-256 |
|---|---|
| `probe-driver.log` | `1ae5b571518c8131ef46247e82a040ec26b020c59a9051bf3fd16665f44756ca` |
| `image-readback.bin` | `f84be4a8d77b9951b64a80b2235b78a85f4124f64d0e1db6bbe1f571d13c8b77` |
| `image-readback.txt` | `0b8ab6c95995d6d04059a3ea742a14c6a1959b277c2f399089dc5c223a11de13` |

Local reports: `analysis/image-gpu-result-20261023-005649.json` and
`analysis/image-gpu-evidence-hashes-20261023-005649.json`. The spec and the preparation
manifest were not modified to mark success: their offline states identify the provenance
of the artifact; this result is recorded separately.

## Scope and continuation

Verified: a 2x2 sampled RGBA32F image, one mip, an immutable linear/clamp sampler, and the
mutable heap of the microtest. It does not test other formats, writable images, the mod's
dynamic sampler, nor repeatability across multiple runs. It also does not validate the real
PRE, full FSR, Proton or OptiScaler/Cyberpunk.

The continuation is to reconstruct the formats, sizes and contents of the PRE resources from
the host, and to cover the return of information from the shim context. No PRE is dispatched
with arbitrary resources, and no permission for new GPU tests is inferred on the agent's
own initiative.
