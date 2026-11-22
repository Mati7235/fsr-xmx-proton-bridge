# User checklist: Spider-Man 4.1.2 trace (one page)

Manual run by the user only, in a disposable prefix. Nothing here authorizes
anything by itself; you do each step by hand. Do not touch Steam, real prefixes,
drivers or services.

## 0. Read first (do not copy: reference)

- Full runbook and exact commands: [spiderman-trace-runbook.md](spiderman-trace-runbook.md)
  (§0 paths/versions, §1 re-verification, §2 DLL, §3 preparation, §4 Proton
  command, §5 optional RenderDoc, §6 `evidence/versions/`).
- What to record from the PRE `native_1080` dispatch: [pre-trace-capture-spec.md](pre-trace-capture-spec.md)
  (§1–§8: creation, views/copies, `GetDesc`, pre/post bytes, handles/bases,
  sampler, sequence/context, grid/transitions).
- Which version row to save and with which command: [pre-trace-version-checklist.md](pre-trace-version-checklist.md)
  (the runbook §6 table already adapts it to 4.1.2: DLL `fadbcb50…`, no
  compiled zebin, explicit system ICD).

## 1. Prepare (read-only)

1. Re-verify the starting hashes with runbook §1 (DLL `fadbcb50…`, IR
   `49e069fd…`, envelope `ce372719…`; if they differ, stop).
2. Generate the run with `tools/prepare_trace_capture_412.py` (runbook §3);
   leave the `wineprefix-reserved-not-initialized` uninitialized.

## 2. Mod DLL (manual)

1. Back up the current file outside the game (it is `d0dcccc7…`, not the mod).
2. Copy `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` over it
   in the game folder (exact path in runbook §2).
3. `sha256sum` must give `fadbcb50…`; confirm in the OptiScaler overlay/log
   that the FSR/XMX 4.1.2 backend is in use (runbook §2 step 4).

## 3. Run (manual, once authorized)

1. Proton command only with `evidence/env.json` (environment replaced) + log
   outside the game: see runbook §4 (`VKD3D_DEBUG=trace` already set).
2. Find a scene with 1920×1080 input; note the actual resolution and actual PCI
   (`8086:e20b` expected); expected grid `(120,540,1)` (formula and modes in
   runbook §5 / spec §8).
3. Optional: RenderDoc capture to `<run>/evidence/spiderman-412.rdc` and open
   with `qrenderdoc` (runbook §5); locate the `Dispatch` and the 11+1
   descriptors.

## 4. Evidence (one row per item, value + source)

Fill `runs/<id>/evidence/versions/` with the runbook §6 table (12 rows:
exe, PE version, Proton, VKD3D, Wine, ICD manifest+library, DLL
`fadbcb50…`, PRE IR+envelope, PCI, host). Also save the `vkd3d-trace.log` log,
the `.rdc` if applicable, and pre/post bytes (spec §4: 128 B header of arg 10,
2,112 B of arg 9, record base+{0,16} and the OWORD plane of arg 0;
full dump recommended, not initialized as an empty buffer).

## 5. Closing criterion

The trace is input evidence, not an oracle or a functional test. No row replaces
the oracle; `S_OK`, overlay or magenta prove nothing (runbook §6, spec
"What this capture does not establish").
