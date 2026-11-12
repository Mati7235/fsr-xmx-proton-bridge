#!/usr/bin/env python3
"""Prepare a hash-pinned, CPU-only scaffold for a future authorized PRE caller trace.

Preparation never executes Wine, Vulkan, Mesa, a GPU, or any harness. The
generated launcher refuses to do anything unless passed --run-trace explicitly,
and even then it only verifies hashes and scaffolds fresh per-run directories:
it never initializes a Wine prefix and never spawns a child process (Fase 1).
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid


REPO = Path(__file__).resolve().parents[1]

DLL_SHA256 = "3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53"
DISASSEMBLY_SHA256 = "4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0"
D3D12_HEADER_SHA256 = "23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e"
DXGI_FORMAT_HEADER_SHA256 = "8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48"
PRE_INPUT_SHA256 = "76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b"
PRE_ZEBIN_SHA256 = "3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2"
PRE_CODE_SHA256 = "2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f"
ZE_INFO_SHA256 = "5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c"
IGA_DISASM_SHA256 = "a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660"
IR_SPVASM_SHA256 = "7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e"

PINNED_FILES = {
    "dll": ("artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll", DLL_SHA256),
    "disassembly": ("analysis/fsr-xmx-disassembly.txt", DISASSEMBLY_SHA256),
    "d3d12_header": ("artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/d3d12.h",
                     D3D12_HEADER_SHA256),
    "dxgi_format_header": ("artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/dxgiformat.h",
                           DXGI_FORMAT_HEADER_SHA256),
    "pre_input_envelope": ("analysis/cm-payloads-0001/module-0000.cmspv", PRE_INPUT_SHA256),
    "pre_zebin": ("analysis/offline-pre/full/pre_bmg.bin", PRE_ZEBIN_SHA256),
    "pre_ze_info": ("analysis/offline-pre/full/ze_info.yaml", ZE_INFO_SHA256),
    "pre_iga_disasm": ("analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm", IGA_DISASM_SHA256),
    "pre_ir_spvasm": ("analysis/fsr-resources/xe2-first.spvasm", IR_SPVASM_SHA256),
}

PROFILE_FILES = (
    "profiles/fsr4-pre-native1080-bmg.json",
    "profiles/fsr4-pre-native1080-payload-audit.json",
)

# Heap-relative slot -> (arg, root, BTI). u1/arg1 is the store destination;
# the `.xyz` channel mask 7 of the typed-quad store is not a binding.
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


def check_profile_hashes(label, data):
    for key, expected in (("input_sha256", PRE_INPUT_SHA256),
                          ("zebin_sha256", PRE_ZEBIN_SHA256),
                          ("code_sha256", PRE_CODE_SHA256)):
        if data.get(key) != expected:
            raise ValueError(f"{label} pins an unreviewed PRE identity: {key}")
    if data.get("runtime_approved", False) is not False:
        raise ValueError(f"{label} must keep runtime_approved=false")


def validate_icd_manifest(path):
    manifest_path = regular_file(path, "local ICD manifest")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"local ICD manifest is not readable JSON: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("ICD"), dict):
        raise ValueError("local ICD manifest has an unexpected schema")
    if data.get("file_format_version") not in {"1.0.0", "1.0.1"}:
        raise ValueError("unsupported local ICD manifest format version")
    api_version = data["ICD"].get("api_version")
    if not isinstance(api_version, str) or re.fullmatch(r"\d+\.\d+\.\d+", api_version) is None:
        raise ValueError("local ICD manifest has no valid API version")
    library = data["ICD"].get("library_path")
    if not isinstance(library, str):
        raise ValueError("local ICD manifest has no library_path string")
    library_path = regular_file(library, "local Mesa ICD library")
    return data, manifest_path, library_path


def prepare(output_root=None, icd_manifest=None):
    pinned = {}
    for label, (relative, expected) in PINNED_FILES.items():
        path = regular_file(REPO / relative, label)
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"Unreviewed {label} SHA-256: {actual}")
        pinned[label] = path
    profiles = {}
    for relative in PROFILE_FILES:
        path = regular_file(REPO / relative, f"PRE profile {relative}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"PRE profile {relative} is not readable JSON: {exc}")
        if not isinstance(data, dict):
            raise ValueError(f"PRE profile {relative} has an unexpected root type")
        check_profile_hashes(relative, data)
        profiles[relative] = (path, data)

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
               "note": "A local ICD manifest must be supplied at authorization time via --icd-manifest; system ICDs are not valid."}

    if output_root is None:
        output_root = REPO / "build" / f"trace-pre-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    output_root = Path(output_root).absolute()
    output_root.mkdir(parents=True, exist_ok=False)

    files = {label: {"path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
             for label, path in sorted(pinned.items())}
    for relative, (path, _) in sorted(profiles.items()):
        files[f"profile/{relative}"] = {"path": str(path), "sha256": sha256(path),
                                        "size_bytes": path.stat().st_size}
    files["spec/pre-trace-capture-spec.md"] = {
        "path": str(regular_file(REPO / "docs/pre-trace-capture-spec.md", "capture spec")),
        "sha256": sha256(REPO / "docs/pre-trace-capture-spec.md"),
        "size_bytes": (REPO / "docs/pre-trace-capture-spec.md").stat().st_size}
    files["spec/pre-trace-version-checklist.md"] = {
        "path": str(regular_file(REPO / "docs/pre-trace-version-checklist.md", "version checklist")),
        "sha256": sha256(REPO / "docs/pre-trace-version-checklist.md"),
        "size_bytes": (REPO / "docs/pre-trace-version-checklist.md").stat().st_size}

    manifest = {
        "schema_version": 1,
        "kind": "pre-caller-trace-scaffold",
        "status": "prepared-trace-ready-not-executed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "CPU-only preparation for a future authorized D3D12 caller trace (PRE native_1080). No Wine/GPU execution occurred or is implied.",
        "capture_spec": "docs/pre-trace-capture-spec.md",
        "version_checklist": "docs/pre-trace-version-checklist.md",
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
        },
        "run_policy": {
            "explicit_flag_required": "--run-trace",
            "fresh_run_directory_required": True,
            "fresh_wineprefix_directory_reserved_only": True,
            "wineprefix_is_not_initialized": True,
            "environment_is_replaced_not_inherited": True,
            "launcher_spawns_no_child_process": True,
            "local_icd_manifest_required": True,
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    launcher = output_root / "run-manual.py"
    launcher.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'tools')!r})\n"
        "import prepare_trace_capture\n"
        f"raise SystemExit(prepare_trace_capture.launch_cli({str(manifest_path)!r}))\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return output_root


def verify_manifest(manifest):
    if manifest.get("kind") != "pre-caller-trace-scaffold":
        raise ValueError("manifest is not a recognized PRE trace preparation")
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
    }


PLANNED_COMMAND_TEMPLATE = """\
FUTURE AUTHORIZED TRACE ONLY — Fase 1 does not execute this.

Scaffolded run directory: {run_dir}
Reserved (NOT initialized) Wine prefix: {prefix}
Effective environment (isolated, minimal): evidence/env.json
Pinned input hashes: evidence/pinned-hashes.json
ICD manifest in force: {icd_manifest}

Manual steps once authorized (disposable prefix, never Steam/real prefixes):
1. Fill in <EXE-PATH>, <PROTON-BUILD-DIR> and <VKD3D-BUILD> actually used.
2. Record every row of docs/pre-trace-version-checklist.md under evidence/versions/.
3. From a shell with ONLY the variables in evidence/env.json set, run the caller
   under <PROTON-BUILD-DIR> with WINEPREFIX={prefix}, capturing per
   docs/pre-trace-capture-spec.md (IDs, views, slots 0-10, GetDesc, bytes
   arg9/arg10/arg0, sampler, context sequence, Dispatch grid, pre/post dumps).
4. Preserve the original capture next to evidence/ and never edit it.

This launcher never initializes Wine and never spawns the traced process.
"""


def launch(manifest_path, run_trace=False, icd_manifest=None, run_id=None):
    if not run_trace:
        raise ValueError("refusing to scaffold; pass --run-trace explicitly for this manual trace preparation")
    manifest_path = regular_file(manifest_path, "preparation manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest(manifest)

    icd = manifest.get("icd", {})
    if icd.get("status") == "pinned-explicit-local-icd":
        icd_manifest_path = regular_file(icd["manifest"], "pinned ICD manifest")
    else:
        if icd_manifest is None:
            raise ValueError("no local ICD pinned at preparation; pass --icd-manifest with an explicit local ICD manifest")
        _, icd_manifest_path, _ = validate_icd_manifest(icd_manifest)

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
                                        icd_manifest=icd_manifest_path),
        encoding="utf-8")
    (evidence / "icd-manifest.json").write_text(
        Path(icd_manifest_path).read_text(encoding="utf-8"), encoding="utf-8")
    return run_dir, env


def launch_cli(manifest_path, argv=None):
    parser = argparse.ArgumentParser(description="Scaffold isolated per-run dirs for a future authorized PRE trace (never executes it)")
    parser.add_argument("--run-trace", action="store_true", help="explicitly authorize scaffolding this manual trace run")
    parser.add_argument("--icd-manifest", type=Path, help="explicit local ICD manifest (required unless pinned at preparation)")
    parser.add_argument("--run-id", help="fixed run directory name (default: timestamped)")
    args = parser.parse_args(argv)
    try:
        run_dir, _ = launch(manifest_path, run_trace=args.run_trace,
                             icd_manifest=args.icd_manifest, run_id=args.run_id)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Scaffolded trace run (nothing executed): {run_dir}")
    print("Reserved WINEPREFIX was created empty and NOT initialized.")
    print("Next (only once authorized): follow evidence/planned-command.txt and docs/pre-trace-version-checklist.md.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="new output directory under build/trace-pre-*; must not already exist")
    parser.add_argument("--icd-manifest", type=Path, help="optional explicit local ICD manifest to pin now")
    args = parser.parse_args(argv)
    try:
        output = prepare(args.out, args.icd_manifest)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Prepared CPU-only trace scaffold: {output / 'run-manual.py'}")
    print("No Wine/GPU execution occurred. Manual scaffold command: "
          f"python3 {output / 'run-manual.py'} --run-trace [--icd-manifest <local-icd.json>]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
