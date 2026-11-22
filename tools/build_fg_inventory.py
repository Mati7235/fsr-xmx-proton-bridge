#!/usr/bin/env python3
"""Build analysis/fg-401-static/inventory.json from a FidelityFX frame-generation DLL.

Composes tools/inspect_fg.py (PE, resources, DXBC, keywords, entropy) and
tools/fg_shader_census.py (per-container DXIL program version and kernel names),
then characterises the large non-DXBC regions found between shader containers
(header/table layout, float16 plausibility, duplication).

Static only: the input image is never loaded or executed.
"""
import argparse
import collections
import json
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fg_shader_census  # noqa: E402
import inspect_fg  # noqa: E402


def fp16_stats(blob: bytes) -> dict:
    n = len(blob) // 2
    values = struct.unpack_from("<%de" % n, blob, 0)
    nan = inf = big = 0
    decades = collections.Counter()
    for value in values:
        if value != value:
            nan += 1
            continue
        if value in (float("inf"), float("-inf")):
            inf += 1
            continue
        magnitude = abs(value)
        if magnitude > 100:
            big += 1
        if magnitude > 0:
            decades[int(math.floor(math.log10(magnitude)))] += 1
    return {
        "values": n,
        "nan": nan,
        "inf": inf,
        "abs_gt_100": big,
        "decade_histogram": {str(k): v for k, v in sorted(decades.items())},
    }


def region_table(blob: bytes):
    """Locate a run of 32-byte records {u32 x, u32 hash, u32 size, 5x u32 zero}."""
    def record_ok(offset):
        if offset + 32 > len(blob):
            return False
        hash_value, size = struct.unpack_from("<II", blob, offset + 4)
        tail = struct.unpack_from("<5I", blob, offset + 12)
        return hash_value != 0 and size != 0 and not any(tail)

    start = None
    for candidate in range(0, 0x401, 4):
        if all(record_ok(candidate + 32 * i) for i in range(8)):
            start = candidate
            break
    if start is None:
        return 0, [], None
    records = []
    offset = start
    while record_ok(offset):
        _reserved, hash_value, size = struct.unpack_from("<III", blob, offset)
        records.append({"index": len(records),
                        "record_offset": offset,
                        "hash": f"0x{hash_value:08x}",
                        "size": size})
        offset += 32
    return start, records, offset


def payload_bounds(blob: bytes, threshold: int = 100):
    last = None
    for offset in range(0, len(blob) - 4096, 4096):
        words = struct.unpack_from("<2048e", blob, offset)
        bad = sum(1 for w in words if w != w or abs(w) > 1000)
        if bad < threshold:
            last = offset
    return last


def regions(dll: Path) -> list:
    data = dll.read_bytes()
    containers = inspect_fg.dxbc_containers(data)
    gaps = []
    cursor = containers[0]["file_offset"] + containers[0]["size"]
    for container in containers[1:]:
        start = container["file_offset"]
        if start - cursor > 512:
            gaps.append((cursor, start))
        cursor = start + container["size"]
    out = []
    for start, end in gaps:
        blob = data[start:end]
        table_start, table, payload_start = region_table(blob)
        if len(table) < 8:
            table_start, table, payload_start = None, [], None
        last_block = payload_bounds(blob) if payload_start is not None else None
        payload = None
        if payload_start is not None and last_block is not None:
            payload = blob[payload_start:last_block + 4096]
        out.append({
            "file_offset": start,
            "file_offset_hex": f"0x{start:x}",
            "size": end - start,
            "entropy": round(inspect_fg.entropy(blob), 3),
            "sha256": inspect_fg.hashlib.sha256(blob).hexdigest(),
            "first_16_bytes": blob[:16].hex(),
            "compression_magic": next(
                (label for sig, label in inspect_fg.MAGICS if blob.startswith(sig)), None),
            "structured": payload_start is not None,
            "table_start": table_start,
            "table_records": len(table),
            "table": table[:4],
            "payload_start": payload_start,
            "payload_start_hex": f"0x{start + payload_start:x}" if payload_start else None,
            "payload_bytes": len(payload) if payload is not None else None,
            "payload_fp16": fp16_stats(payload) if payload else None,
        })
    return out


def build(dll: Path) -> dict:
    report = inspect_fg.build(dll)
    census = fg_shader_census.census(dll)
    containers = []
    for row in census["containers"]:
        containers.append({
            "file_offset_hex": row["file_offset_hex"],
            "size": row["size"],
            "parts": row["parts"],
            "program": row["program"],
            "kernels": row["kernels"],
            "sha256": row["sha256"],
        })
    families = collections.Counter()
    for row in census["containers"]:
        names = [k["name"] for k in row["kernels"]]
        mlfi = [n for n in names if n.startswith("mlfi_")]
        families[mlfi[0].rsplit("_pass", 1)[0] if mlfi else "non_mlfi"] += 1
    keywords = {}
    for key in ("ml", "neural", "model", "weight", "fp8", "e4m3", "int8", "fp16",
                "wmma", "dot4", "redstone", "optical", "interpolat", "rdna4", "gfx12"):
        rows = report["keywords"].get(key, [])
        keywords[key] = {"count": len(rows), "samples": rows[:5]}
    return {
        "artifact": report["artifact"],
        "sections": report["sections"],
        "exports": report["exports"],
        "imports": report["imports"],
        "resources": report["resources"],
        "versioninfo": report["versioninfo"],
        "shaders": {
            "container_count": census["container_count"],
            "total_bytes": sum(c["size"] for c in containers),
            "raw_dxbc_magic": report["dxbc"]["raw_dxbc_magic_occurrences"],
            "family_counts": dict(families),
            "program_versions": census["program_versions"],
            "containers": containers,
        },
        "embedded_regions": regions(dll),
        "keywords": keywords,
        "entropy_regions": report["entropy_regions"],
        "method": report["method"],
        "limitations": report["limitations"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    text = json.dumps(build(args.dll), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
