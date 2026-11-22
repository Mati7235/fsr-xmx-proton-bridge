# First manual test: DPAS and resource map

**First positive manual run on B580:** see
[result and limits](first-synthetic-gpu-result.md). It does not test FSR,
Proton, OptiScaler or Cyberpunk: it uses a custom synthetic kernel.

## Before running it

- Save your work and close games/GPU loads. A failure can hang the GPU or the
  desktop session. The timeout does not guarantee recovery.
- Do not use `sudo`, do not copy files to Steam and do not change system drivers.
- Run the command only if you accept starting this GPU experiment. The agent did
  not run it for you.

From any directory, on this machine:

```bash
python3 /home/matias/Proyectos/fsr-xmx-proton-bridge/build/lab-test-v02/run-manual.py --run-gpu
```

Without `--run-gpu`, the launcher refuses to run the harness. There is no installation
or persistent environment change. The command prepares HOME, cache and new directories
inside `build/lab-test-v02/runs/`, sets only the local ICD and disables layers.
It reserves a new empty `WINEPREFIX` to meet the laboratory isolation requirement:
the harness is native, it does not initialize Wine or use existing prefixes.
**This does not isolate the hardware or the kernel driver.**

## What it checks

Before creating the process, the launcher verifies the SHA-256 of the harness, driver,
ICD and probe files. If they changed, it aborts: do not edit the manifest to skip
the check. The preparation also reproduced the restricted audit of the payload and
compared the full CMK3 against the expected package.

On the GPU, the harness requires PCI `8086:e20b`, a canary, DIRECT layout with a
non-zero stride, injection/dispatch logs and 128 results for each of the eleven
resources. It also checks that the remaining five slots do not change. Creating the
pipeline or seeing a marker alone is not considered success.

If it completes correctly, the harness prints:

```text
GPU probe passed its gating, canary, injection-log, deterministic readback, and untouched-buffer checks.
```

The launcher prints the exit code and the run directory. The results are saved in
`build/lab-test-v02/runs/<ejecución>/evidence/`:

- `icd-selection.txt`: requested loader configuration.
- `anv_canary`, `canary-driver.log`, `canary-evidence.txt`: driver control.
- `probe-driver.log`: injection and dispatch evidence.
- `probe-readback.txt`: values and untouched slots checked.

Send me the terminal output and those logs, even if it seems to work. A partial
readback file does not demonstrate success; check the exit code and the complete
evidence. If it fails or hangs, do not test it directly in Cyberpunk and do not change
the checks to force it to pass.

## Offline re-preparation

If you rebuild or hashes change, you can generate a new preparation without running
the GPU, from the repository root:

```bash
python3 tools/prepare_lab_test.py
```

It will use the local Mesa, the local harness and `build/lab-probe-v10`. The output
directory is new and the program prints the corresponding manual command. It does not
install or redistribute binaries. This preparation does not validate dynamic
dependency resolution or the runtime: those checks remain part of the experiment.
