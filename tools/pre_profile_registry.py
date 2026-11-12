#!/usr/bin/env python3
"""Offline profile-per-hash selector for the LOCAL CMK3 prototype.

Only kernels whose reviewed native code hash is listed in
profiles/registry.json may use the explicit CMK3 layout; every other kernel
keeps the legacy CMK2 path, so global XeSS behavior is unchanged. This module
never installs, builds, or runs kernels: it only selects reviewed metadata.

registry_gen() is a stable FNV-1a 32-bit digest of the canonical registry
content. tools/build_anv_mapping_patch.py embeds it into the candidate ANV
reader (anv_cm_toolchain_gen), so any registry/profile change invalidates
previously cached kernels without touching the legacy path.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "profiles/registry.json"


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def registry_gen(registry: dict | None = None) -> str:
    """Stable 8-hex FNV-1a digest of the canonical registry content."""
    data = _canonical(registry if registry is not None else load())
    h = 2166136261
    for byte in data:
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"


def load(path: Path = REGISTRY) -> dict:
    registry = json.loads(path.read_text())
    if registry.get("schema_version") != 1:
        raise ValueError("Unsupported profile registry schema")
    if registry.get("status") != "experimental-offline-only":
        raise ValueError("Profile registry is not marked experimental-offline-only")
    entries = registry.get("profiles")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Profile registry lists no kernels")
    seen = set()
    for entry in entries:
        for key in ("kernel", "code_sha256", "profile",
                    "table_pc_base", "expected_push_size", "surface_count"):
            if key not in entry:
                raise ValueError(f"Registry entry misses {key!r}")
        code = entry["code_sha256"]
        if not isinstance(code, str) or len(code) != 64 or code in seen:
            raise ValueError("Registry code_sha256 must be unique 64-hex digests")
        seen.add(code)
        base, expected = entry["table_pc_base"], entry["expected_push_size"]
        if (type(base) is not int or type(expected) is not int
                or not 0 <= base < expected <= 256 or base % 4 or expected % 4):
            raise ValueError("Registry push layout must be 4-byte aligned")
        profile_path = ROOT / entry["profile"]
        if not profile_path.is_file():
            raise ValueError(f"Registry profile missing: {entry['profile']}")
    return registry


def find_profile(code_sha256: str, registry: dict | None = None) -> dict | None:
    """Return the reviewed registry entry for native code, or None (legacy path)."""
    entries = (registry if registry is not None else load())["profiles"]
    for entry in entries:
        if entry["code_sha256"] == code_sha256:
            return entry
    return None


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code_sha256", help="SHA-256 of the native kernel code")
    args = parser.parse_args()
    entry = find_profile(args.code_sha256)
    if entry is None:
        print("no reviewed profile: keep the legacy CMK2 path")
        return 1
    print(json.dumps(entry, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
