# Readback methodology: what each comparison proves and what it does not

Tool: `tools/fsr_readback_compare.py` (CPU only, standard library only with an
optional fast path in numpy). This note defines how to read its results once we
have RenderDoc captures of FSR 4 XMX. It does not use em dashes.

## 1. Bit-for-bit determinism between two runs (`diff` without tolerance)

What it proves: repeatability. Two captures with the same inputs, same
driver, same weights and same resolution must produce identical bytes.
`diff a.bin b.bin` exits with 0 and `identical: True` only if the files are
bit-for-bit equal.

What it does not prove: correctness. An upscaler can be perfectly deterministic
and still produce a wrong image (wrong weights, corrupted LUT, constant UV
offset). Determinism is a necessary condition for debugging, not evidence of quality.

Reading notes:

- `--tolerance ABS` separates two different questions: "differs in bits" from
  "differs beyond a tolerance". With tolerance, output 0 means agreement within
  the threshold even if there are different bits (for example after format
  conversion). Without tolerance, any differing bit gives output 1.
- `-0.0` against `0.0` differs in bits but has absolute error 0; the tool
  reports it as a bit difference within tolerance 0.
- NaN against any value (even another NaN with a different payload) counts as a
  difference with infinite error. Two deterministic runs should never produce
  diverging NaNs; if they appear, the problem is earlier (see `inspect`).

## 2. Quality plausibility against a reference (`metrics`)

What it proves: plausibility. `metrics candidato.bin referencia.bin` computes
PSNR and SSIM per channel and on luminance. The reference here is a comparison
upscaling available on Linux (XeSS or native TAAU), not AMD. A high PSNR and an
SSIM close to 1 indicate that the candidate reconstructs detail in a way
similar to a reasonable upscaler.

What it does not prove: equivalence with AMD. No PSNR/SSIM threshold against
XeSS demonstrates that FSR 4 XMX is correct, because we do not have its output
on AMD hardware to compare against. It only rules out gross failures (flat
screen, noise, half resolution, permuted channels).

Relevant design decisions:

- Peak signal: by default 1.0 for float formats and 255.0 for 8-bit formats;
  it can be forced with `--peak`. PSNR is always reported together with the
  MSE so the number can be reinterpreted with another peak.
- SSIM: mean over non-overlapping 8x8 box windows (edges use partial windows),
  with K1=0.01, K2=0.03 and L equal to the peak. A box 8x8 was chosen over an
  11x11 Gaussian because it is exact with O(1) memory in pure Python; an 11x11
  Gaussian with overlap would require convolutions that would take minutes in
  pure stdlib at 1080p. The window used is printed in every run (`ssim_window:`).
- Luminance: Rec.709 (0.2126 R + 0.7152 G + 0.0722 B) for RGB/RGBA; for
  1- or 2-channel formats the first channel is used. Alpha is reported per
  channel but never enters the luminance: broken alpha must not sink the image
  quality metric, and identical alpha must not inflate it.
- NaN/Inf make `metrics` fail with exit 2 and an explicit message. PSNR and
  SSIM are not defined with non-finite values, and averaging them would hide
  that; the correct flow is `inspect` first, `metrics` afterwards.

## 3. Why there is no bit-exact oracle for FSR 4 without AMD hardware

A bit-exact oracle would require reproducing the same arithmetic as the
hardware: same order of operations in every reduction, same rounding of each
XMX matrix instruction, same quantized weights and the same driver
microcode. None of that is public for FSR 4, and the neural network only exists
as Windows binaries over XMX. On a different GPU (RDNA, NVIDIA, Intel iGPU) the
equivalent instructions reorder and round differently, so not even a perfect
reimplementation of the algorithm would give identical bytes.

What would be needed to have it: a reference output capture generated on real
AMD hardware with fixed inputs (the input/output pair as test vectors), or AMD
publishing reference vectors. With that, `diff` with tolerance 0 against the
oracle would be the equivalence proof; without it, the evidentiary ceiling is point 2.

## 4. How it combines with the existing injection evidence

The project's success criterion remains conjunctive. Each leg discards a
different class of false positive:

1. Injection (`review_image_result.py` and driver evidence): proves that our
   code ran on the correct dispatch and that the raw buffer output matches the
   synthetic contract. It says nothing about visual quality.
2. Determinism (`diff`): proves that the upscaler is repeatable between runs.
   Without this, any quality metric is noise.
3. Plausibility (`metrics` against XeSS or TAAU): proves that the reconstructed
   image resembles a reasonable upscaling. Without this, a deterministic but
   visually broken pipeline would pass.
4. Human eye on crops: no metric replaces looking at edges, text and
   high-frequency areas, where global PSNR/SSIM average out and hide local artifacts.

None of these legs alone, not even all four together, proves equivalence with
FSR 4 on AMD hardware. They prove that the bridge performs repeatable and
visually plausible upscaling under the test's control.

## 5. How the dumps are obtained

The mod already has its own GPU readback, so RenderDoc is not needed for
this. `run-full-test.sh` (in the disposable run, git-ignored) sets up the
environment and summarizes the results.

```bash
cd build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6
./run-full-test.sh int8 oracle1 --oracle-all --proton-log --dry-run   # revisar primero
./run-full-test.sh int8 oracle1 --oracle-all --proton-log
./run-full-test.sh int8 oracle2 --oracle-all --proton-log
```

The two runs must be the same area, resolution and preset: the dump is
one-shot on the first useful frame, so different scenes give different tensors
by content, not by model.

Variables it uses, verified in the mod binary:

| Variable | Effect |
|---|---|
| `FSR4_XMX_P1..P12_OracleCaptureReadback=1` | arms the one-shot dump of the pass |
| `MLSR-XMX-PASSn-ORACLE-DUMP=<ruta Windows>` | directory for `pN_input.bin` / `pN_output.bin` |
| `MLSR-XMX-PRE-PARITY=1` and `MLSR-XMX-PRE-PARITY-DIR` | parity of the PRE tensor against the stock path |
| `MLSR-XMX-PRE-HOSTPARITY=1`, `MLSR-XMX-PRE-POSTSTORE-PARITY=1` | additional hash checks |

Names with hyphens cannot be passed with `export`: the script injects them with
`env` when launching Proton.

The `summary.txt` of each run reports `oracle-armed`, `oracle-captured`,
`oracle-files`, `pre-parity-exact` and `pre-parity-mismatch`. Afterwards:

```bash
python3 tools/fsr_readback_compare.py inspect results/oracle1-*/oracle/p9_output.bin --format rgba32f --width 1920 --height 1080
python3 tools/fsr_readback_compare.py diff results/oracle1-*/oracle/p9_output.bin results/oracle2-*/oracle/p9_output.bin
```

If the tensor's format and dimensions do not match what was assumed,
`inspect` fails with exit 2 instead of inventing an interpretation.
