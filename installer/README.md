# `fsr-xmx` installer (v1)

A bash script plus two small Python helpers (standard library only). No `sudo`:
everything lives under your home folder.

## Files

- `fsr-xmx`: the program itself (`installer/fsr-xmx`).
- `lib/common.sh`: shared functions (profiles, backups, checksums).
- `lib/ini_edit.py`: edits keys in `OptiScaler.ini` by section, leaving the
  rest of the bytes and the CRLF line endings untouched.
- `lib/vdf.py`: rewrites `compatibilitytool.vdf` for the Steam tool.
- `profiles/cyberpunk2077.conf`: reference profile (appid 1091500,
  `bin/x64`, pinned checksums for mod/fsr-original/OptiScaler/ANR).

## What the ready-made package must contain (`install --from <dir>`)

```text
MANIFEST                                  VERSION=...
SHA256SUMS                                <hash>  <relative path>
icd/intel_icd.json
lib/libvulkan_intel.so
igdext64.dll
cabinet.dll
vkd3d-proton/x86_64-windows/d3d12.dll
vkd3d-proton/x86_64-windows/d3d12core.dll
tools/cm-compile.sh
```

`install` checks **every** file listed in `SHA256SUMS` before copying
anything, copies to `~/.local/share/fsr-xmx/versions/<VERSION>/`, and only then
switches the `current` link in one step. If anything doesn't match, it leaves
nothing half-done.

## Folder layout it uses

```text
~/.local/share/fsr-xmx/
  current -> versions/<VERSION>/
  versions/<VERSION>/
  profiles/<game>/state.conf           written by `enable`
  .fsr-xmx-root                        marker: "installed by fsr-xmx"
~/.cache/fsr-xmx/<appid>/kernels       ANV_CM_KERNEL_DIR
~/.cache/fsr-xmx/<appid>/logs          PROTON_LOG_DIR
<game>/.fsr-xmx-backup/<date>/         copies of overwritten files + manifest.tsv
```

## Tests

`python3 -I -m unittest discover -s tests -p 'test_installer.py' -v`

Everything runs in temporary folders with fake `HOME`/`XDG_*`; it never touches
real Steam, prefixes or games.
