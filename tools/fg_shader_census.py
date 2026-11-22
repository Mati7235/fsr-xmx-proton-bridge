#!/usr/bin/env python3
"""Census of DXBC/DXIL shader containers and their kernel names in a PE image.

Reuses tools/inspect_fg.py for container discovery. For each container it
reports the DXIL program version (shader kind + model), the part list, and any
kernel-name strings found inside the container byte range.

Static only: the input image is never loaded or executed.
"""
import argparse
import collections
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import inspect_fg  # noqa: E402

KINDS = {
    0: "pixel",
    1: "vertex",
    2: "geometry",
    3: "hull",
    4: "domain",
    5: "compute",
    6: "library",
    7: "mesh",
    8: "amplification",
}

NAME_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{3,63}")


def decode_program_version(data: bytes, chunk: dict):
    """DXIL part: u32 program version, u32 offset/count, 'DXIL', bitcode header."""
    pos = chunk["file_offset"]
    if pos + 12 > len(data):
        return None
    version, = struct.unpack_from("<I", data, pos)
    kind = (version >> 16) & 0xFFFF
    major = (version >> 4) & 0xF
    minor = version & 0xF
    return {
        "raw": f"0x{version:08x}",
        "kind_id": kind,
        "kind": KINDS.get(kind, f"unknown:{kind}"),
        "major": major,
        "minor": minor,
        "shader_model": f"{major}.{minor}",
    }


def kernel_names(data: bytes, start: int, size: int):
    names = []
    for m in NAME_RE.finditer(data[start:start + size]):
        text = m.group(0).decode("ascii", "replace")
        if "_pass" in text or text.startswith("ffx_") or text.startswith("mlfi"):
            names.append({"file_offset": start + m.start(), "name": text})
    seen = {}
    for row in names:
        seen.setdefault(row["name"], row["file_offset"])
    return [{"name": k, "file_offset": v} for k, v in seen.items()]


def census(dll: Path) -> dict:
    data = dll.read_bytes()
    containers = inspect_fg.dxbc_containers(data)
    rows = []
    for c in containers:
        dxil = next((ch for ch in c["chunks"] if ch["fourcc"] == "DXIL"), None)
        rows.append({
            "file_offset": c["file_offset"],
            "file_offset_hex": c["file_offset_hex"],
            "size": c["size"],
            "parts": c["parts"],
            "program": decode_program_version(data, dxil) if dxil else None,
            "kernels": kernel_names(data, c["file_offset"], c["size"]),
            "sha256": c["sha256"],
        })
    families = collections.Counter()
    for r in rows:
        names = [k["name"] for k in r["kernels"]]
        mlfi = [n for n in names if n.startswith("mlfi_")]
        if mlfi:
            families[mlfi[0].rsplit("_pass", 1)[0]] += 1
        else:
            families["other"] += 1
    programs = collections.Counter(
        f"{r['program']['kind']}_{r['program']['shader_model']}"
        for r in rows if r["program"])
    return {
        "artifact": {
            "path": str(dll.resolve()),
            "sha256": inspect_fg.hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        },
        "container_count": len(rows),
        "family_counts": dict(families),
        "program_versions": dict(programs),
        "containers": rows,
        "limitations": [
            "Kernel names are recovered from printable strings inside each container; "
            "absence of a name is not evidence of absence.",
            "Program version comes from the DXIL part header, not from execution.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = census(args.dll)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
