#!/usr/bin/env python3
"""Prepare a hash-pinned, CPU-only scaffold for a future authorized XMX 4.1.2 PRE trace.

Spider-Man Remastered + OptiScaler (Dx12Upscaler=xess) + Proton Experimental,
explicit Intel ICD. CPU-only preparation.

Preparation never executes Wine, Vulkan, Mesa, a GPU, the game, or any
harness. The generated launcher refuses to do anything unless passed BOTH
--run-trace AND --icd-manifest explicitly, and even then it only verifies
hashes and scaffolds fresh per-run directories under build/trace-412-*/: it
never initializes a Wine prefix and never spawns a child process (Fase 1).

Pinned 4.1.2 identity (verified locally by SHA-256):

- DLL ``artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll``:
  ``fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732``
- Six packs ``analysis/fsr-xmx-412/pack-4010{1..6}.raw`` (raw SHA-256 per
  profiles/xmx412-pins.json; 252+252+378+716+312+67 = 1977 CM envelopes).
- PRE Xe2 ``native_1080`` = record 0 of pack-40102.raw (offset 0):
  IR ``49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568``
  (358776 B), envelope
  ``ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab``
  (358873 B), also materialized as
  ``analysis/xmx412-pre-native1080/module-0000.cmspv``.
- Spec ``docs/pre-trace-capture-spec.md`` + checklist
  ``docs/pre-trace-version-checklist.md`` (recorded by hash; the checklist
  still shows old-DLL values, so the runbook records 4.1.2 actuals as
  explicit deviations, never by editing the checklist).
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid


REPO = Path(__file__).resolve().parents[1]

DLL_SHA256_412 = "fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732"
DLL_SIZE_412 = 45558272

# (resource_id, file, raw_size, raw_sha256, res_size, res_sha256, cm_envelopes, bucket)
PACKS_412 = (
    (40101, "analysis/fsr-xmx-412/pack-40101.raw", 35346326,
     "4c63d10c83ed371b30a15ed563e560d0c977d473c7237b7f296e6d78aa88ab8d",
     6107632, "8e260219b64694f1d5aa6020632b0d107abff759f200a728b788aed454e9b9b5",
     252, "18-variant DG2 (SIMD8 DPAS)"),
    (40102, "analysis/fsr-xmx-412/pack-40102.raw", 23682325,
     "d88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491",
     3856836, "58557640463eeec42c0b9ea923d6b7462af2c38e97976be55c9e3501134d7651",
     252, "18-variant Xe2 (SIMD16 DPAS)"),
    (40103, "analysis/fsr-xmx-412/pack-40103.raw", 42034337,
     "a3731f5b65fb077e34a605e46931abb8988b9924989a1476fe29586ab70eb7d5",
     6960934, "48963849d7b456256fb4e238353be436d6bb17b8385e8cb7857bb901f929f458",
     378, "FSR 4.1.2 Lite (DG2)"),
    (40104, "analysis/fsr-xmx-412/pack-40104.raw", 42477193,
     "a9ea6724ebe4079a29c819564baeb15815cbd2df15cf7d9752be80ac4e7054ea",
     8031050, "2c93c489f21415d4e8505b466669d529f1e397a4d0c9e6790acef326d9d25fa1",
     716, "DLSS K (DG2 + Xe2/Xe3)"),
    (40105, "analysis/fsr-xmx-412/pack-40105.raw", 19590261,
     "7ac547ee7bc0fce49b55036cad6993d41a42b1077aa911e6acff91b357d246fa",
     3421152, "4cff7b12f864d69abf851ae8e88883475116fe80f1ad7841b955d6f9e90acb2f",
     312, "DLSS E / F"),
    (40106, "analysis/fsr-xmx-412/pack-40106.raw", 5443681,
     "03c188585417648a051d2b32258a0a6d554d58ab8969bdcc9c0919435a331ac3",
     1001522, "579f610f8dba82752bdc130ed1de27b1abc4ff432f9963d419d038862d20b0de",
     67, "DLSS-MX (DG2)"),
)

PRE_PACK_RESOURCE_ID = 40102
PRE_RECORD_INDEX = 0
PRE_OFFSET = 0
PRE_IR_SIZE = 358776
PRE_TRAILER_SIZE = 97
PRE_ENVELOPE_SIZE = 358873
PRE_IR_SHA256_412 = "49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568"
PRE_ENVELOPE_SHA256_412 = "ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab"
PRE_OPTION_A = "-vc-payload -Xfinalizer '-noDPASMacro'"
PRE_OPTION_B = " -target-features=+ocl_runtime"
PRE_CMSPV = "analysis/offline-pre-412/module-0000.cmspv"

PINS_412 = "profiles/xmx412-pins.json"

D3D12_HEADER_SHA256 = "23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e"
DXGI_FORMAT_HEADER_SHA256 = "8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48"

GAME_DIR = Path(os.environ.get("SPIDERMAN_DIR", Path.home() / "Juegos" / "Spiderman" / "Marvel's Spider-Man Remastered"))
GAME_EXE = GAME_DIR / "Spider-Man.exe"
OPTISCALER_INI = GAME_DIR / "OptiScaler.ini"
GAME_DLL_SLOT = GAME_DIR / "amd_fidelityfx_upscaler_dx12.dll"
GAME_DLL_SLOT_NOTE = (
    "OptiScaler.ini [Upscalers] Dx12Upscaler=xess; [Resources] FfxDx12SRPath=auto, "
    "so OptiScaler resolves amd_fidelityfx_upscaler_dx12.dll from the game directory. "
    "The mod DLL (fadbcb50...) belongs exactly at this path; the stock file there "
    "(d0dcccc7...) is NOT the mod."
)
PROTON_DIR = Path(os.environ.get("PROTON_EXPERIMENTAL_DIR", Path.home() / ".steam" / "root" / "steamapps" / "common" / "Proton - Experimental"))
EXPLICIT_ICD = Path("/usr/share/vulkan/icd.d/intel_icd.x86_64.json")

PINNED_FILES = {
    "dll_412": ("artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll",
                DLL_SHA256_412, DLL_SIZE_412),
    "pre_envelope_cmspv": (PRE_CMSPV, PRE_ENVELOPE_SHA256_412, PRE_ENVELOPE_SIZE),
    "d3d12_header": ("artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/d3d12.h",
                     D3D12_HEADER_SHA256, None),
    "dxgi_format_header": ("artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/dxgiformat.h",
                           DXGI_FORMAT_HEADER_SHA256, None),
}

# Heap-relative slot -> (arg, root, BTI). u1/arg1 is the store destination;
# the `.xyz` channel mask 7 of the typed-quad store is not a binding.
# Shape matches the 4.1.2 SPIR-V census: 2 Buffer RW + 1 Image RW + 7 Image RO
# + 2 Buffer RW + sampler (docs/xmx412-toolchain.md, tests/test_xmx412_spirv.py).
SLOT_MAP = [
    {"heap_slot": 0, "arg": 2, "root": 3, "bti": 1, "role": "t0 ReadOnly image"},
    {"heap_slot": 1, "arg": 3, "root": 4, "bti": 2, "role": "t1 ReadOnly image"},
    {"heap_slot": 2, "arg": 4, "root": 5, "bti": 3, "role": "t2 ReadOnly image"},
    {"heap_slot": 3, "arg": 5, "root": 6, "bti": 4, "role": "t3 ReadOnly image"},
    {"heap_slot": 4, "arg": 6, "root": 7, "bti": 5, "role": "t4 ReadOnly image"},
    {"heap_slot": 5, "arg": 7, "root": 8, "bti": 6, "role": "t5 ReadOnly image"},
    {"heap_slot": 6, "arg": 8, "root": 9, "bti": 7, "role": "t6 ReadOnly image"},
    {"heap_slot": 7, "arg": 0, "root": 1, "bti": 8, "role": "u0 mixed buffer (UAV R8_UINT, NumElements=Width)"},
    {"heap_slot": 8, "arg": 1, "root": 2, "bti": 9, "role": "u1 destination image (ReadWrite)"},
    {"heap_slot": 9, "arg": 9, "root": 10, "bti": 10, "role": "t7 buffer (SRV R8_UINT, 2112 B)"},
    {"heap_slot": 10, "arg": 10, "root": 11, "bti": 11, "role": "t8 header buffer (SRV R8_UINT, 128 B)"},
]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular, non-symlink file: {path}")
    return path.resolve()


def check_pins_412(data):
    if not isinstance(data, dict):
        raise ValueError("xmx412 pins file has an unexpected root type")
    if data.get("source_dll_sha256") != DLL_SHA256_412:
        raise ValueError("xmx412 pins file does not pin the 4.1.2 DLL fadbcb50...")
    by_id = {p["resource_id"]: p for p in data.get("packs", [])}
    for resource_id, _, _, raw_sha, res_size, res_sha, envelopes, _ in PACKS_412:
        entry = by_id.get(resource_id)
        if entry is None:
            raise ValueError(f"xmx412 pins file is missing pack {resource_id}")
        if entry.get("raw_sha256") != raw_sha or entry.get("res_sha256") != res_sha:
            raise ValueError(f"xmx412 pins file disagrees on pack {resource_id} hashes")
        if entry.get("res_size") != res_size or entry.get("cm_envelopes") != envelopes:
            raise ValueError(f"xmx412 pins file disagrees on pack {resource_id} sizes/counts")


def verify_pre_block_412():
    """Fail-closed structural check of the 4.1.2 PRE native_1080 block.

    Read-only parse of pack-40102.raw record 0 with the stdlib footer parser.
    No DLL is loaded, nothing is executed.
    """
    import parse_cm_payloads

    pack_path = regular_file(REPO / "analysis/fsr-xmx-412/pack-40102.raw",
                             "4.1.2 Xe2 pack 40102")
    data = pack_path.read_bytes()
    records = parse_cm_payloads.parse(data)
    if len(records) != 252:
        raise ValueError(f"4.1.2 pack 40102 envelope count drift: {len(records)}")
    record = records[PRE_RECORD_INDEX]
    for key, expected in (("offset", PRE_OFFSET), ("ir_size", PRE_IR_SIZE),
                          ("trailer_size", PRE_TRAILER_SIZE),
                          ("envelope_size", PRE_ENVELOPE_SIZE),
                          ("ir_sha256", PRE_IR_SHA256_412),
                          ("envelope_sha256", PRE_ENVELOPE_SHA256_412),
                          ("embedded_string_a", PRE_OPTION_A),
                          ("embedded_string_b", PRE_OPTION_B)):
        if record.get(key) != expected:
            raise ValueError(f"4.1.2 PRE native_1080 block drift: {key}")
    blob = data[record["offset"]:record["offset"] + record["ir_size"]]
    if b"fsr4_pre_xmx" not in blob:
        raise ValueError("4.1.2 PRE native_1080 block has no fsr4_pre_xmx entry")
    return pack_path


def validate_icd_manifest(path):
    manifest_path = regular_file(path, "explicit ICD manifest")
    try:
        data = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"explicit ICD manifest is not readable: {exc}")
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"explicit ICD manifest is not valid JSON: {exc}")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ICD"), dict):
        raise ValueError("explicit ICD manifest has an unexpected schema")
    if parsed.get("file_format_version") not in {"1.0.0", "1.0.1"}:
        raise ValueError("unsupported explicit ICD manifest format version")
    api_version = parsed["ICD"].get("api_version")
    if not isinstance(api_version, str) or re.fullmatch(r"\d+\.\d+\.\d+", api_version) is None:
        raise ValueError("explicit ICD manifest has no valid API version")
    library = parsed["ICD"].get("library_path")
    if not isinstance(library, str):
        raise ValueError("explicit ICD manifest has no library_path string")
    library_path = regular_file(library, "explicit ICD library")
    return parsed, manifest_path, library_path


def prepare(output_root=None, icd_manifest=None):
    pinned = {}
    for label, (relative, expected, size) in PINNED_FILES.items():
        path = regular_file(REPO / relative, label)
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"Unreviewed {label} SHA-256: {actual}")
        if size is not None and path.stat().st_size != size:
            raise ValueError(f"Unreviewed {label} size: {path.stat().st_size}")
        pinned[label] = path
    for resource_id, relative, raw_size, raw_sha, _, _, _, _ in PACKS_412:
        path = regular_file(REPO / relative, f"4.1.2 pack {resource_id}")
        if path.stat().st_size != raw_size:
            raise ValueError(f"Unreviewed 4.1.2 pack {resource_id} size")
        if sha256(path) != raw_sha:
            raise ValueError(f"Unreviewed 4.1.2 pack {resource_id} SHA-256")
        pinned[f"pack_{resource_id}"] = path
    verify_pre_block_412()
    pins_path = regular_file(REPO / PINS_412, "4.1.2 pins file")
    try:
        pins_data = json.loads(pins_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"4.1.2 pins file is not readable JSON: {exc}")
    check_pins_412(pins_data)
    pinned["pins_412"] = pins_path

    if icd_manifest is not None:
        _, icd_path, icd_library = validate_icd_manifest(icd_manifest)
        icd = {"status": "pinned-explicit-local-icd",
               "manifest": str(icd_path),
               "manifest_sha256": sha256(icd_path),
               "library_path": str(icd_library),
               "library_sha256": sha256(icd_library)}
    else:
        icd = {"status": "pending-explicit-local-icd",
               "manifest": None,
               "note": ("An explicit ICD manifest must be supplied at launch time via "
                        "--icd-manifest (e.g. " + str(EXPLICIT_ICD) + "); "
                        "system ICD auto-discovery is not valid.")}

    if output_root is None:
        output_root = REPO / "build" / f"trace-412-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    output_root = Path(output_root).absolute()
    output_root.mkdir(parents=True, exist_ok=False)

    try:
        exe_size = GAME_EXE.stat().st_size if GAME_EXE.is_file() else None
    except OSError:
        exe_size = None
    files = {label: {"path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
             for label, path in sorted(pinned.items())}
    files["spec/pre-trace-capture-spec.md"] = {
        "path": str(regular_file(REPO / "docs/pre-trace-capture-spec.md", "capture spec")),
        "sha256": sha256(REPO / "docs/pre-trace-capture-spec.md"),
        "size_bytes": (REPO / "docs/pre-trace-capture-spec.md").stat().st_size}
    files["spec/pre-trace-version-checklist.md"] = {
        "path": str(regular_file(REPO / "docs/pre-trace-version-checklist.md", "version checklist")),
        "sha256": sha256(REPO / "docs/pre-trace-version-checklist.md"),
        "size_bytes": (REPO / "docs/pre-trace-version-checklist.md").stat().st_size}
    files["runbook/docs/spiderman-trace-runbook.md"] = {
        "path": str(regular_file(REPO / "docs/spiderman-trace-runbook.md", "trace runbook")),
        "sha256": sha256(REPO / "docs/spiderman-trace-runbook.md"),
        "size_bytes": (REPO / "docs/spiderman-trace-runbook.md").stat().st_size}

    manifest = {
        "schema_version": 1,
        "kind": "xmx412-pre-caller-trace-scaffold",
        "status": "prepared-trace-ready-not-executed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "notice": ("CPU-only preparation for a future authorized XMX 4.1.2 D3D12 PRE "
                   "caller trace (Spider-Man Remastered, native_1080). No Wine/GPU/game "
                   "execution occurred or is implied."),
        "game": {
            "title": "Marvel's Spider-Man Remastered",
            "exe_path": str(GAME_EXE),
            "exe_size_bytes_observed": exe_size,
            "exe_size_note": "Observed at preparation time only; re-record at trace time, never pinned.",
            "optiscaler_ini": str(OPTISCALER_INI),
            "dx12_upscaler_setting": "xess",
            "dll_slot": str(GAME_DLL_SLOT),
            "dll_slot_note": GAME_DLL_SLOT_NOTE,
            "proton_dir": str(PROTON_DIR),
        },
        "xmx412": {
            "dll_sha256": DLL_SHA256_412,
            "dll_size_bytes": DLL_SIZE_412,
            "packs": [{"resource_id": rid, "bucket": bucket, "raw_size": rsize,
                       "raw_sha256": rsha, "res_size": ressize,
                       "res_sha256": ressha, "cm_envelopes": envs}
                      for rid, _, rsize, rsha, ressize, ressha, envs, bucket in PACKS_412],
            "pre_native1080": {
                "pack_resource_id": PRE_PACK_RESOURCE_ID,
                "record_index": PRE_RECORD_INDEX,
                "offset": PRE_OFFSET,
                "ir_size": PRE_IR_SIZE,
                "trailer_size": PRE_TRAILER_SIZE,
                "envelope_size": PRE_ENVELOPE_SIZE,
                "ir_sha256": PRE_IR_SHA256_412,
                "envelope_sha256": PRE_ENVELOPE_SHA256_412,
            },
        },
        "capture_spec": "docs/pre-trace-capture-spec.md",
        "version_checklist": "docs/pre-trace-version-checklist.md",
        "runbook": "docs/spiderman-trace-runbook.md",
        "runtime_approved": False,
        "gpu_executed": False,
        "wine_initialized": False,
        "roots": {"repo": str(REPO)},
        "icd": icd,
        "files": files,
        "slot_map": SLOT_MAP,
        "expected_dispatch": {
            "geometry_formula": "x=(w+15)>>4; x+=x&1; y=h>>1 with w=*(ctx+0x840), h=*(ctx+0x844)",
            "native_1080_grid": [120, 540, 1],
            "b0_root_constant": 0,
            "arg0_uav_minimum_bytes": 8294400,
            "descriptor_tables": 11,
            "sampler_root": 12,
        },
        "run_policy": {
            "explicit_flags_required": ["--run-trace", "--icd-manifest"],
            "fresh_run_directory_required": True,
            "fresh_wineprefix_directory_reserved_only": True,
            "wineprefix_is_not_initialized": True,
            "environment_is_replaced_not_inherited": True,
            "launcher_spawns_no_child_process": True,
            "explicit_icd_manifest_required": True,
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    launcher = output_root / "run-manual.py"
    launcher.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'tools')!r})\n"
        "import prepare_trace_capture_412\n"
        f"raise SystemExit(prepare_trace_capture_412.launch_cli({str(manifest_path)!r}))\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return output_root


def verify_manifest(manifest):
    if manifest.get("kind") != "xmx412-pre-caller-trace-scaffold":
        raise ValueError("manifest is not a recognized XMX 4.1.2 PRE trace preparation")
    if manifest.get("status") != "prepared-trace-ready-not-executed":
        raise ValueError("manifest is not a prepared-not-executed trace scaffold")
    for label, item in manifest["files"].items():
        path = regular_file(item["path"], label)
        if sha256(path) != item["sha256"]:
            raise ValueError(f"SHA-256 changed since preparation: {label} ({path})")
    icd = manifest.get("icd", {})
    if icd.get("status") == "pinned-explicit-local-icd":
        manifest_path = regular_file(icd["manifest"], "pinned ICD manifest")
        if sha256(manifest_path) != icd["manifest_sha256"]:
            raise ValueError("pinned ICD manifest changed since preparation")
        library_path = regular_file(icd["library_path"], "pinned ICD library")
        if sha256(library_path) != icd["library_sha256"]:
            raise ValueError("pinned ICD library changed since preparation")


def minimal_env(run_dir, prefix, icd_manifest_path):
    run_dir = Path(run_dir)
    return {
        "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
        "HOME": str(run_dir / "home"),
        "XDG_CACHE_HOME": str(run_dir / "cache"),
        "XDG_CONFIG_HOME": str(run_dir / "config"),
        "XDG_DATA_HOME": str(run_dir / "data"),
        "XDG_STATE_HOME": str(run_dir / "state"),
        "TMPDIR": str(run_dir / "tmp"),
        "WINEPREFIX": str(prefix),
        "VK_DRIVER_FILES": str(icd_manifest_path),
        "VK_ICD_FILENAMES": str(icd_manifest_path),
        "VKD3D_DEBUG": "trace",
    }


PLANNED_COMMAND_TEMPLATE = """\
FUTURE AUTHORIZED TRACE ONLY — Fase 1 does not execute this.
XMX 4.1.2 PRE trace, Spider-Man Remastered (OptiScaler Dx12Upscaler=xess).

Scaffolded run directory: {run_dir}
Reserved (NOT initialized) Wine prefix: {prefix}
Effective environment (isolated, minimal): evidence/env.json
Pinned input hashes: evidence/pinned-hashes.json
ICD manifest in force: {icd_manifest}
Game executable: {exe}
Proton build: {proton} (use "<proton>/proton run")

Manual steps once authorized (disposable prefix, never Steam/real prefixes;
full procedure in docs/spiderman-trace-runbook.md):
1. Place the 4.1.2 mod DLL (fadbcb50...) at the OptiScaler slot
   <game>/amd_fidelityfx_upscaler_dx12.dll (FfxDx12SRPath=auto); back up the
   stock file first and re-verify with sha256sum. Confirm in the OptiScaler
   overlay/log which backend actually handles the upscale before capturing.
2. Record every row of docs/pre-trace-version-checklist.md under
   evidence/versions/ (DLL row = fadbcb50...; PRE rows = ir 49e069fd... /
   envelope ce372719...; checklist deviations annotated, never edited in).
3. From a shell with ONLY the variables in evidence/env.json set
   (VKD3D_DEBUG=trace included), run:
     "<proton>/proton" run "{exe}"
   capturing per docs/pre-trace-capture-spec.md (IDs, views, slots 0-10,
   GetDesc, bytes arg9/arg10/arg0, sampler, context sequence, Dispatch grid
   (120,540,1), pre/post dumps). Redirect the VKD3D trace log into the run
   directory, never into the game or Steam prefixes.
4. Optional frame capture with renderdoccmd (v1.46 present) wrapping the same
   proton command; any extra layer variable is a documented deviation from
   evidence/env.json.
5. Preserve the original capture next to evidence/ and never edit it.

This launcher never initializes Wine and never spawns the traced process.
"""


def launch(manifest_path, run_trace=False, icd_manifest=None, run_id=None):
    if not run_trace:
        raise ValueError("refusing to scaffold; pass --run-trace explicitly for this manual trace preparation")
    if icd_manifest is None:
        raise ValueError("refusing to scaffold; pass --icd-manifest with an explicit local ICD manifest")
    manifest_path = regular_file(manifest_path, "preparation manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest(manifest)

    _, icd_manifest_path, _ = validate_icd_manifest(icd_manifest)
    pinned = manifest.get("icd", {})
    if pinned.get("status") == "pinned-explicit-local-icd":
        if sha256(icd_manifest_path) != pinned["manifest_sha256"]:
            raise ValueError("provided --icd-manifest does not match the ICD pinned at preparation")

    base = manifest_path.parent / "runs"
    base.mkdir(exist_ok=True)
    name = run_id or (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    run_dir = base / name
    run_dir.mkdir(mode=0o700, exist_ok=False)
    prefix = run_dir / "wineprefix-reserved-not-initialized"
    evidence = run_dir / "evidence"
    for directory in (run_dir / "home", run_dir / "cache", run_dir / "config",
                      run_dir / "data", run_dir / "state", run_dir / "tmp",
                      prefix, evidence, evidence / "versions"):
        directory.mkdir(mode=0o700)
    if any(prefix.iterdir()):
        raise ValueError("reserved Wine prefix directory is not empty; refusing to continue")

    env = minimal_env(run_dir, prefix, icd_manifest_path)
    (evidence / "env.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    (evidence / "pinned-hashes.json").write_text(
        json.dumps(manifest["files"], indent=2) + "\n", encoding="utf-8")
    (evidence / "planned-command.txt").write_text(
        PLANNED_COMMAND_TEMPLATE.format(run_dir=run_dir, prefix=prefix,
                                        icd_manifest=icd_manifest_path,
                                        exe=manifest["game"]["exe_path"],
                                        proton=manifest["game"]["proton_dir"]),
        encoding="utf-8")
    (evidence / "icd-manifest.json").write_text(
        Path(icd_manifest_path).read_text(encoding="utf-8"), encoding="utf-8")
    return run_dir, env


def launch_cli(manifest_path, argv=None):
    parser = argparse.ArgumentParser(description="Scaffold isolated per-run dirs for a future authorized XMX 4.1.2 PRE trace (never executes it)")
    parser.add_argument("--run-trace", action="store_true", help="explicitly authorize scaffolding this manual trace run")
    parser.add_argument("--icd-manifest", type=Path, help="explicit local ICD manifest (always required)")
    parser.add_argument("--run-id", help="fixed run directory name (default: timestamped)")
    args = parser.parse_args(argv)
    try:
        run_dir, _ = launch(manifest_path, run_trace=args.run_trace,
                             icd_manifest=args.icd_manifest, run_id=args.run_id)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Scaffolded XMX 4.1.2 trace run (nothing executed): {run_dir}")
    print("Reserved WINEPREFIX was created empty and NOT initialized.")
    print("Next (only once authorized): follow evidence/planned-command.txt and docs/spiderman-trace-runbook.md.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="new output directory under build/trace-412-*; must not already exist")
    parser.add_argument("--icd-manifest", type=Path, help="optional explicit ICD manifest to pin now (still required again at launch)")
    args = parser.parse_args(argv)
    try:
        output = prepare(args.out, args.icd_manifest)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Prepared CPU-only XMX 4.1.2 trace scaffold: {output / 'run-manual.py'}")
    print("No Wine/GPU/game execution occurred. Manual scaffold command: "
          f"python3 {output / 'run-manual.py'} --run-trace --icd-manifest <explicit-local-icd.json>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
