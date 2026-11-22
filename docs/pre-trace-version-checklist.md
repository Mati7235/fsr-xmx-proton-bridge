# Version checklist for the future authorized PRE trace

Phase 1, CPU-only: this list defines **what to record**; it does not authorize the trace.
The user fills it in by hand at the time of the manual run, in a disposable prefix,
without touching Steam, real prefixes, drivers or services. All retrieval commands are
read-only.

## How to record

- One row per item: observed value + source (path or file) + SHA-256 when it is a file.
- Save the evidence under `runs/<id>/evidence/versions/` next to the capture
  ([spec](pre-trace-capture-spec.md)).
- If an item does not apply or is not found, note it explicitly instead of omitting it.
  Do not reuse values from another machine or run.

## Record table

| # | Item | Source / read-only command | Evidence to save |
|---|---|---|---|
| 1 | Game executable (real path used) | path + `sha256sum <exe>` + size in bytes | `exe.sha256`, path noted |
| 2 | Executable version | PE version resource (FileVersion/ProductVersion), read without running | `exe.version.txt` |
| 3 | Proton build in use (directory) | Proton directory path + contents of its version file | `proton.version.txt` |
| 4 | D3D12/VKD3D binaries actually loaded | `d3d12`/VKD3D DLLs of the build in use, confirmed by the load log + `sha256sum` of each | `vkd3d.*.sha256` |
| 5 | VKD3D-Proton version | version string of the build in use (version file or log), without assuming a number | `vkd3d.version.txt` |
| 6 | Wine version of the prefix | `wine --version` of the Wine that manages the disposable prefix (read-only, outside Steam) | `wine.version.txt` |
| 7 | Local ICD manifest used | `intel-local-icd.json` from the preparation (path + `sha256sum`) | copy in `evidence/` |
| 8 | Local ICD library (`libvulkan_intel.so`) | absolute path + `sha256sum` + `api_version` from the manifest | `icd.library.sha256` |
| 9 | XMX mod DLL | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` (re-verify with `sha256sum`, do not assume) | `dll.sha256` |
| 10 | PRE Xe2 native_1080 blob | `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2` (re-verify) | `pre-zebin.sha256` |
| 11 | Observed PCI device | `8086:e20b` expected on B580; record the real ID from the device-selection log | `device.pci.txt` |
| 12 | Kernel and desktop (context, does not change the result) | `uname -r`, CachyOS/Mesa version of the system, as context only | `host.context.txt` |

## Rules

- The preparation manifest pins the hashes of the DLL, disassembly, headers and PRE blob;
  the launcher re-verifies them before scaffolding the run. If any changed, the trace does
  not proceed: do not edit the manifest to skip the check.
- The ICD must be an explicit local manifest (`VK_DRIVER_FILES` and `VK_ICD_FILENAMES`
  pointing only to it). A system ICD is not valid for this capture.
- `WINEPREFIX` is a fresh directory per run, reserved but **not initialized** by the
  preparation. Initialization, if authorized, happens only inside the future manual run.
- No item in this list substitutes for the output oracle nor proves functional correctness
  (see [controlled contract](pre-controlled-test-contract.md)).
