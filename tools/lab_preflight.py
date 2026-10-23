#!/usr/bin/env python3
"""Inventory local Mesa/probe build outputs without running them or touching a GPU."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


PROBE_FILES = (
    "probe.spvasm",
    "probe.spv",
    "probe_bmg.bin",
    "disasm/.text.bridge_probe.asm",
    "wg1_1_5.cmk",
    "placeholder.spv",
    "canary.spv",
    "summary.json",
    "probe-spec.json",
)
MESA_FILES = (
    "src/intel/vulkan/libvulkan_intel.so",
    "meson-info/intro-projectinfo.json",
    "meson-info/intro-buildoptions.json",
    "meson-info/intro-targets.json",
)
PROBE_KIND = "synthetic-dpas-resource-map-probe-not-fsr"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root, relative_paths):
    """Hash only the named evidence files; never recursively scan build trees."""
    entries = []
    for relative in relative_paths:
        path = root / relative
        entry = {"path": relative, "exists": path.is_file() and not path.is_symlink()}
        if entry["exists"]:
            entry.update(size_bytes=path.stat().st_size, sha256=sha256(path))
        entries.append(entry)
    return entries


def read_json(path, label, blockers):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        blockers.append(f"{label} no es JSON legible: {exc}")
        return None


def make_manifest(mesa_build, probe_dir):
    blockers = []
    mesa_build = Path(mesa_build).resolve()
    probe_dir = Path(probe_dir).resolve()
    mesa_files = inventory(mesa_build, MESA_FILES)
    probe_files = inventory(probe_dir, PROBE_FILES)

    for root, label in ((mesa_build, "Mesa build"), (probe_dir, "probe")):
        if not root.is_dir():
            blockers.append(f"No existe el directorio {label}: {root}")
    for entry in mesa_files:
        if not entry["exists"]:
            blockers.append(f"Falta evidencia de Mesa: {mesa_build / entry['path']}")
    for entry in probe_files:
        if not entry["exists"]:
            blockers.append(f"Falta artefacto del probe: {probe_dir / entry['path']}")

    project = read_json(mesa_build / "meson-info/intro-projectinfo.json", "metadata Meson", blockers)
    if project is not None and not isinstance(project, dict):
        blockers.append("metadata Meson: formato raíz inesperado")
    options = read_json(mesa_build / "meson-info/intro-buildoptions.json", "opciones Meson", blockers)
    if options is not None and not isinstance(options, list):
        blockers.append("opciones Meson: se esperaba una lista")
    targets = read_json(mesa_build / "meson-info/intro-targets.json", "targets Meson", blockers)
    if targets is not None and not isinstance(targets, list):
        blockers.append("targets Meson: se esperaba una lista")

    spec = read_json(probe_dir / "probe-spec.json", "probe-spec", blockers)
    if spec is not None:
        if not isinstance(spec, dict):
            blockers.append("probe-spec: formato raíz inesperado")
        else:
            if spec.get("kind") != PROBE_KIND:
                blockers.append("probe-spec no identifica el probe sintético conocido; no es FSR")
            if spec.get("gpu_validated") is not False:
                blockers.append("probe-spec debe declarar gpu_validated=false")
            required_contract = {
                "target_vendor_id": "0x8086",
                "target_device_id": "0xe20b",
                "resource_heap_slots": [7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10],
                "untouched_heap_slots": [11, 12, 13, 14, 15],
                "surfaces": 11,
                "words_per_surface": 128,
                "cm_local_size": [1, 1, 1],
                "hardware_local_size": [32, 1, 1],
                "expected_right_mask": "0xffffffff",
                "push_size": 52,
                "table_pc_base": 4,
            }
            for key, expected in required_contract.items():
                if spec.get(key) != expected:
                    blockers.append(f"probe-spec.{key} no coincide con el contrato esperado ({expected!r})")
            code_hash = spec.get("code_sha256")
            if not isinstance(code_hash, str) or re.fullmatch(r"[0-9a-fA-F]{64}", code_hash) is None:
                blockers.append("probe-spec.code_sha256 ausente o no es un SHA-256 hexadecimal de 64 caracteres")

    disasm_path = probe_dir / "disasm/.text.bridge_probe.asm"
    if disasm_path.is_file() and not disasm_path.is_symlink():
        try:
            if "dpas." not in disasm_path.read_text(encoding="utf-8", errors="replace"):
                blockers.append("La desensamblación del probe no evidencia una instrucción DPAS")
        except OSError as exc:
            blockers.append(f"No se pudo leer la desensamblación del probe: {exc}")

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "cpu-only-inventory-not-semantic-binary-validation",
        "roots": {"mesa_build": str(mesa_build), "probe": str(probe_dir)},
        "mesa": {
            "files": mesa_files,
            "project_metadata": project,
            "build_options_metadata_present": (mesa_build / "meson-info/intro-buildoptions.json").is_file(),
            "targets_metadata_present": (mesa_build / "meson-info/intro-targets.json").is_file(),
            "validation": "pending-independent-build-and-mask-dimensions-review",
        },
        "probe": {
            "files": probe_files,
            "kind": spec.get("kind") if isinstance(spec, dict) else None,
            "gpu_validated": False,
            "is_fsr_kernel": False,
        },
        "fsr": {
            "complete_kernel_present": False,
            "bridge_ready": False,
            "runtime_test_authorized": False,
        },
        "preflight": {
            "status": "blocked" if blockers else "inventory-complete-review-required",
            "blockers": blockers,
            "gpu_executed": False,
            "binary_semantics_verified": False,
            "runtime_ready": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesa-build", type=Path, required=True, help="Directorio de build Meson ya compilado")
    parser.add_argument("--probe-dir", type=Path, required=True, help="Salida local del build_lab_probe.py")
    parser.add_argument("--out", type=Path, required=True, help="Ruta de salida del manifiesto JSON")
    args = parser.parse_args(argv)

    manifest = make_manifest(args.mesa_build, args.probe_dir)
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{manifest['preflight']['status']}: {output}")
    if manifest["preflight"]["blockers"]:
        for blocker in manifest["preflight"]["blockers"]:
            print(f"- {blocker}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
