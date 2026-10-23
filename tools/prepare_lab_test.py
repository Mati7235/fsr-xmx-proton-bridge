#!/usr/bin/env python3
"""Prepare a hash-pinned, CPU-only manifest and opt-in isolated lab launcher.

Preparation never executes the harness, Vulkan, Mesa, or a GPU. The generated
launcher refuses to run unless passed --run-gpu explicitly.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

import lab_preflight


REPO = Path(__file__).resolve().parents[1]
DEFAULT_MESA = REPO / "build/mesa-26.1.2/out"
DEFAULT_PROBE = REPO / "build/lab-probe-v10"
DEFAULT_HARNESS = REPO / "build/lab-harness/bridge_probe"
ICD_RELATIVE = "src/intel/vulkan/libvulkan_intel.so"
ICD_TEMPLATE = "src/intel/vulkan/intel_icd.x86_64.json"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular, non-symlink file: {path}")
    return path.resolve()


def validate_cmk3(path, spec):
    data = path.read_bytes()
    # apply_cmk_mapping.py defines the local CMK3 extension at byte 472:
    # explicit-table-base flag followed by the reviewed push-constant size.
    if len(data) < 480 or data[:4] != b"CMK3":
        raise ValueError("probe CMK must contain a complete CMK3 header and extension")
    code_size = int.from_bytes(data[4:8], "little")
    if len(data) != 480 + code_size:
        raise ValueError("CMK3 code size does not match file length")
    mapping = tuple(int.from_bytes(data[offset:offset+4], "little") for offset in (168, 172, 176))
    if mapping != (0, 0, 4):
        raise ValueError("CMK3 requires explicit heap set 0, binding 0, table base 4")
    if data[472:480] != (1).to_bytes(4, "little") + int(spec["push_size"]).to_bytes(4, "little"):
        raise ValueError("CMK3 explicit heap/push-size extension differs from probe-spec")
    if sha256_bytes(data[480:]) != spec.get("code_sha256"):
        raise ValueError("CMK3 native-code SHA-256 differs from probe-spec")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def regenerate_probe_audit(probe_dir):
    """Re-run the probe's restricted CPU audit over its current local inputs."""
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import build_lab_probe

    generated = build_lab_probe.audit_probe_payload(
        (probe_dir / "probe_bmg.bin").read_bytes(),
        (probe_dir / "disasm/.text.bridge_probe.asm").read_text(encoding="utf-8"),
        (probe_dir / "embedded-probe.spvasm").read_text(encoding="utf-8"),
    )
    recorded = json.loads((probe_dir / "payload-audit.json").read_text(encoding="utf-8"))
    if generated != recorded:
        raise ValueError("regenerated restricted probe audit differs from payload-audit.json")
    return generated


def prepare(mesa_build=DEFAULT_MESA, probe_dir=DEFAULT_PROBE, harness=DEFAULT_HARNESS,
            output_root=None):
    mesa_build = Path(mesa_build).resolve()
    probe_dir = Path(probe_dir).resolve()
    harness = regular_file(harness, "harness")
    preflight = lab_preflight.make_manifest(mesa_build, probe_dir)
    if preflight["preflight"]["blockers"]:
        raise ValueError("preflight blocked: " + "; ".join(preflight["preflight"]["blockers"]))
    if preflight["preflight"]["status"] != "inventory-complete-review-required":
        raise ValueError("unexpected preflight status; refusing preparation")

    spec = json.loads((probe_dir / "probe-spec.json").read_text(encoding="utf-8"))
    validate_cmk3(probe_dir / "wg1_1_5.cmk", spec)
    audit = regenerate_probe_audit(probe_dir)
    from build_lab_probe import pack_probe
    expected_cmk, _ = pack_probe((probe_dir / "probe_bmg.bin").read_bytes(), audit)
    if (probe_dir / "wg1_1_5.cmk").read_bytes() != expected_cmk:
        raise ValueError("CMK3 bytes differ from the audited probe's expected complete packet")
    mesa_library = regular_file(mesa_build / ICD_RELATIVE, "local Mesa ICD library")

    # Use the exact generated ICD manifest template from this Mesa build. It is
    # an input value only; the absolute local library path replaces /usr/lib.
    template_path = regular_file(mesa_build / ICD_TEMPLATE, "Mesa ICD template")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    if not isinstance(template, dict) or not isinstance(template.get("ICD"), dict):
        raise ValueError("local Mesa ICD template has an unexpected schema")
    api_version = template["ICD"].get("api_version")
    if not isinstance(api_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", api_version):
        raise ValueError("local Mesa ICD template has no valid API version")
    icd = {
        "file_format_version": template.get("file_format_version"),
        "ICD": {"api_version": api_version, "library_path": str(mesa_library)},
    }
    if icd["file_format_version"] not in {"1.0.0", "1.0.1"}:
        raise ValueError("unsupported local ICD manifest format version")

    if output_root is None:
        output_root = REPO / "build" / f"lab-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    output_root = Path(output_root).absolute()
    output_root.mkdir(parents=True, exist_ok=False)
    icd_path = output_root / "intel-local-icd.json"
    icd_path.write_text(json.dumps(icd, indent=2) + "\n", encoding="utf-8")

    paths = {"harness": harness, "mesa_icd_library": mesa_library}
    paths.update({f"probe/{entry}": regular_file(probe_dir / entry, f"probe artifact {entry}")
                  for entry in lab_preflight.PROBE_FILES})
    # The extra SPIR-V disassembly is consumed by the audit regeneration.
    paths["probe/embedded-probe.spvasm"] = regular_file(probe_dir / "embedded-probe.spvasm", "embedded SPIR-V disassembly")
    paths["mesa/meson-info/intro-projectinfo.json"] = regular_file(mesa_build / "meson-info/intro-projectinfo.json", "Mesa project metadata")
    paths["mesa/meson-info/intro-buildoptions.json"] = regular_file(mesa_build / "meson-info/intro-buildoptions.json", "Mesa build options")
    paths["mesa/meson-info/intro-targets.json"] = regular_file(mesa_build / "meson-info/intro-targets.json", "Mesa targets")
    paths["icd_manifest"] = icd_path.resolve()
    manifest = {
        "schema_version": 1,
        "status": "prepared-manual-opt-in-not-gpu-validated",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "Preparation is CPU-only. This is a synthetic probe, not FSR; no GPU result is implied.",
        "roots": {"mesa_build": str(mesa_build), "probe": str(probe_dir), "harness": str(harness)},
        "preflight": preflight["preflight"],
        "probe_audit_regenerated": True,
        "probe_audit_status": audit["status"],
        "gpu_executed": False,
        "gpu_validated": False,
        "fsr_complete_kernel_present": False,
        "icd": {"manifest": str(icd_path.resolve()), "api_version": api_version,
                "library_path": str(mesa_library)},
        "files": {key: {"path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
                  for key, path in sorted(paths.items())},
        "run_policy": {
            "explicit_flag_required": "--run-gpu",
            "fresh_run_directory_required": True,
            "fresh_wineprefix_directory_reserved_only": True,
            "wineprefix_is_not_initialized": True,
            "environment_is_replaced_not_inherited": True,
            "gpu_timeout_limitations": "Harness has no timeout for Vulkan setup/compile/submit; fence timeout cannot guarantee recovery from a GPU hang.",
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    launcher = output_root / "run-manual.py"
    launcher.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "import prepare_lab_test\n"
        f"raise SystemExit(prepare_lab_test.launch_cli({str(manifest_path)!r}))\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return output_root


def verify_manifest(manifest):
    for label, item in manifest["files"].items():
        path = Path(item["path"])
        regular_file(path, label)
        if sha256(path) != item["sha256"]:
            raise ValueError(f"SHA-256 changed since preparation: {label} ({path})")
    icd_path = Path(manifest["icd"]["manifest"])
    icd = json.loads(icd_path.read_text(encoding="utf-8"))
    if icd.get("ICD", {}).get("library_path") != manifest["icd"]["library_path"]:
        raise ValueError("ICD library path differs from the pinned manifest")


def launch(manifest_path, run_gpu=False, run_id=None, run_subprocess=subprocess.run):
    if not run_gpu:
        raise ValueError("refusing to launch; pass --run-gpu explicitly for a manual GPU experiment")
    manifest_path = regular_file(manifest_path, "preparation manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "prepared-manual-opt-in-not-gpu-validated":
        raise ValueError("manifest is not a recognized prepared lab test")
    verify_manifest(manifest)
    base = manifest_path.parent / "runs"
    base.mkdir(exist_ok=True)
    name = run_id or (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    run_dir = base / name
    run_dir.mkdir(mode=0o700, exist_ok=False)
    home = run_dir / "home"
    cache = run_dir / "cache"
    config = run_dir / "config"
    data = run_dir / "data"
    state = run_dir / "state"
    tmp = run_dir / "tmp"
    prefix = run_dir / "wineprefix-reserved-not-initialized"
    log_dir = run_dir / "evidence"
    for directory in (home, cache, config, data, state, tmp, prefix):
        directory.mkdir(mode=0o700)

    roots = manifest["roots"]
    args = [manifest["files"]["harness"]["path"], "--run-gpu",
            "--probe-dir", roots["probe"], "--log-dir", str(log_dir),
            "--icd-manifest", manifest["icd"]["manifest"], "--icd-root", roots["mesa_build"]]
    env = {
        "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
        "HOME": str(home), "XDG_CACHE_HOME": str(cache), "XDG_CONFIG_HOME": str(config),
        "XDG_DATA_HOME": str(data), "XDG_STATE_HOME": str(state), "TMPDIR": str(tmp),
        "WINEPREFIX": str(prefix),
        "VK_DRIVER_FILES": manifest["icd"]["manifest"],
        "VK_ICD_FILENAMES": manifest["icd"]["manifest"],
    }
    return run_subprocess(args, env=env, check=False), run_dir


def launch_cli(manifest_path, argv=None):
    parser = argparse.ArgumentParser(description="Launch the isolated GPU harness only with explicit opt-in")
    parser.add_argument("--run-gpu", action="store_true", help="explicitly authorize this manual GPU experiment")
    args = parser.parse_args(argv)
    try:
        result, run_dir = launch(manifest_path, run_gpu=args.run_gpu)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Harness exit code: {result.returncode}; run evidence directory: {run_dir}")
    print("This synthetic probe is not FSR; a process exit code alone is not GPU validation.")
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesa-build", type=Path, default=DEFAULT_MESA)
    parser.add_argument("--probe-dir", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--harness", type=Path, default=DEFAULT_HARNESS)
    parser.add_argument("--out", type=Path, help="new output directory; must not already exist")
    args = parser.parse_args(argv)
    try:
        output = prepare(args.mesa_build, args.probe_dir, args.harness, args.out)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ImportError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Prepared CPU-only manual launcher: {output / 'run-manual.py'}")
    print("No harness/GPU execution occurred. Manual opt-in command: "
          f"python3 {output / 'run-manual.py'} --run-gpu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
