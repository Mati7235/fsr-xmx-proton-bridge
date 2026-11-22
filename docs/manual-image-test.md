# Second manual test: image and sampler

**First positive GPU run:** see [result and limits](first-image-gpu-result.md).
It checks the real sampling of a 2x2 texture with linear filtering and clamp
edges. It is a custom kernel, not the PRE or full FSR. It does not use
Cyberpunk, OptiScaler or Proton.

Save your work and close games/GPU loads: a failure can hang the GPU or the
session. The timeout does not guarantee recovery. Do not use `sudo`.

## Run on this machine

```bash
python3 /home/matias/Proyectos/fsr-xmx-proton-bridge/build/image-test-v01/run-manual.py --run-gpu
```

The flag authorizes that specific manual run. Without it the launch is refused.
The agent did not run the harness or the GPU during preparation.

Before invoking the harness, the hashes of the driver, ICD, harness, kernel,
markers, audit and CPU reference are verified. A new HOME/cache is created per run
and only the local ICD is used. No drivers are installed and no existing Steam or
prefixes are altered. A new empty `WINEPREFIX` is reserved without initializing Wine;
the harness is native. There is no hardware isolation from the desktop.

## What it must check

- PCI `8086:e20b`, mutable descriptor extension and linear RGBA32F support.
- Canary of the adapted driver and no changes in the other words.
- CM injection and DIRECT layout before the target kernel dispatch.
- 64 float32 image values against the CPU reference, including centers,
  interpolation and edges; absolute tolerance `1e-5`, NaN rejected.
- The other 1,984 buffer words remain sentinel, including the output tail.

The v16 preparation fixes the SPIR-V order, sampling signature, channel order,
heap indices and the sampler flag of the package. Do not use attempts v01–v15.
The static audit is restricted and does not replace this experiment.

If it passes, the harness prints:

```text
Image probe passed canary, injection/layout gates, all 64 oracle samples, and sentinel checks.
```

The launcher also prints the exit code and the path of the run under
`build/image-test-v01/runs/`. Send me that output and the path, whether it passes or
fails. There is no need to paste the binary content into the chat.

## Evidence and independent CPU inspection

In `runs/ID-DE-EJECUCION/evidence/` you will find the canary, ICD selection, injection and
dispatch logs, `image-readback.txt` and **`image-readback.bin`**. The latter contains
the 16 complete buffers (8,192 bytes), not just a report that they matched.
It allows the values to be checked again without running the GPU or relying only on
the C comparator.

From the repository root, optionally:

```bash
python3 tools/review_image_result.py \
  --manifest build/image-test-v01/manifest.json \
  --evidence-dir "build/image-test-v01/runs/ID-DE-EJECUCION/evidence"
```

Replace `ID-DE-EJECUCION` with the path the launcher printed. The reviewer also
requires the canary/injection/map logs and the current hashes of the preparation.
A correct readback without that evidence is not accepted as proof of this path.
Do not delete controls or move to Cyberpunk to get around a failure.

## Regenerate only the preparation

If files change or you rebuild, from the root:

```bash
python3 tools/prepare_image_test.py --probe-dir build/image-probe-v16
```

This only regenerates the audit, compares the full CMK3 package and prepares new
ICD/manifest/launcher. It does not run the C or Vulkan code. It prints a manual
command for the new directory; it never overwrites a previous preparation.
