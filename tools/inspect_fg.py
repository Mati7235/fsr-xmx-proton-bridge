#!/usr/bin/env python3
"""Static inventory of FidelityFX frame-generation DLLs (Python standard library).

Reuses PE helpers from tools/inspect_dll_412.py without modifying it and adds:
sections with entropy, resource leaves with file offsets, DXBC/DXIL container
census with part lists, keyword census with file offsets, and high-entropy
region detection with compression-magic checks.

The input DLL is never loaded or executed.
"""
import argparse
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import inspect_dll_412 as inv  # noqa: E402

KEYWORDS = (
    "ml", "mlfg", "neural", "model", "weight", "fp8", "e4m3", "e5m2", "int8",
    "fp16", "wmma", "wavematrix", "dot4", "redstone", "optical", "flow",
    "interpolat", "rdna4", "gfx12", "version", "shader",
)

MAGICS = (
    (b"\x0a\x51\xe5\xc0", "msc-lzms-envelope"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"\x04\x22\x4d\x18", "lz4-frame"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"BZh", "bzip2"),
    (b"\x1f\x8b\x08", "gzip"),
    (b"MSCF", "cab"),
    (b"PK\x03\x04", "zip"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"DXBC", "dxbc"),
    (b"BC\xc0\xde", "llvm-bitcode"),
)


def entropy(blob: bytes) -> float:
    if not blob:
        return 0.0
    counts = [0] * 256
    for byte in blob:
        counts[byte] += 1
    total = len(blob)
    return -sum(c / total * math.log2(c / total) for c in counts if c)


def pe_sections(data: bytes):
    layout = inv._pe_layout(data)
    (pe_off,) = struct.unpack_from("<I", data, 0x3C)
    coff = pe_off + 4
    num_sections, = struct.unpack_from("<H", data, coff + 2)
    opt_size, = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    image_base = struct.unpack_from("<Q" if layout["is_plus"] else "<I", data, opt + 24)[0]
    entry_rva, = struct.unpack_from("<I", data, opt + 16)
    sections = []
    for n in range(num_sections):
        off = opt + opt_size + 40 * n
        name = data[off:off + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, off + 8)
        chars, = struct.unpack_from("<I", data, off + 36)
        blob = data[raw:raw + rawsize] if rawsize else b""
        sections.append({
            "name": name,
            "va": f"0x{va:x}",
            "rva": f"0x{va:x}",
            "virtual_size": vsize,
            "raw_offset": raw,
            "raw_offset_hex": f"0x{raw:x}",
            "raw_size": rawsize,
            "characteristics": f"0x{chars:08x}",
            "entropy": round(entropy(blob), 3),
        })
    return {
        "image_base": f"0x{image_base:x}",
        "entry_point_rva": f"0x{entry_rva:x}",
        "sections": sections,
    }


def parse_exports(data: bytes, image_base: int):
    layout = inv._pe_layout(data)
    rva, _size = layout["data_directory"](0)
    if not rva:
        return []
    off = layout["rva_to_offset"](rva, 40)
    (_chars, _ts, _vmaj, _vmin, _name_rva, base, _nfunc, nname,
     addr_func, addr_names, addr_ord) = struct.unpack_from("<IIHHIIIIIII", data, off)
    exports = []
    for i in range(nname):
        (name_rva,) = struct.unpack_from(
            "<I", data, layout["rva_to_offset"](addr_names + i * 4, 4))
        name_off = layout["rva_to_offset"](name_rva, 8)
        end = data.find(b"\x00", name_off)
        name = data[name_off:end].decode("ascii", "replace")
        (idx,) = struct.unpack_from(
            "<H", data, layout["rva_to_offset"](addr_ord + i * 2, 2))
        (func_rva,) = struct.unpack_from(
            "<I", data, layout["rva_to_offset"](addr_func + idx * 4, 4))
        exports.append({
            "ordinal": base + idx,
            "name": name,
            "rva": f"0x{func_rva:x}",
            "va": f"0x{image_base + func_rva:x}",
        })
    exports.sort(key=lambda e: e["ordinal"])
    return exports


def resource_leaves(data: bytes):
    """Resource leaves with their file offset (extract_resources drops offsets)."""
    (pe_off,) = struct.unpack_from("<I", data, 0x3C)
    magics = struct.unpack_from("<H", data, pe_off + 24)[0]
    is_plus = magics == 0x20B
    num_sections, = struct.unpack_from("<H", data, pe_off + 6)
    opt_size, = struct.unpack_from("<H", data, pe_off + 20)
    opt = pe_off + 24
    directory = opt + (112 if is_plus else 96)
    res_rva, res_size = struct.unpack_from("<II", data, directory + 16)
    if not res_rva or not res_size:
        return []
    layout = inv._pe_layout(data)
    base = layout["rva_to_offset"](res_rva, res_size)
    leaves = []
    seen = set()

    def walk(rel, path):
        if rel in seen:
            raise ValueError("resource directory cycle")
        seen.add(rel)
        off = base + rel
        named, ids = struct.unpack_from("<HH", data, off + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from("<II", data, off + 16 + i * 8)
            if name & 0x80000000:
                rel2 = name & 0x7FFFFFFF
                length, = struct.unpack_from("<H", data, base + rel2)
                label = data[base + rel2 + 2:base + rel2 + 2 + length * 2].decode(
                    "utf-16le", "replace")
            else:
                label = name
            sub = path + [label]
            if target & 0x80000000:
                walk(target & 0x7FFFFFFF, sub)
            else:
                rva, size, codepage, _res = struct.unpack_from("<IIII", data, base + target)
                pos = layout["rva_to_offset"](rva, size) if size else 0
                blob = data[pos:pos + size]
                leaves.append({
                    "type": sub[0] if len(sub) > 0 else None,
                    "name": sub[1] if len(sub) > 1 else None,
                    "language": sub[2] if len(sub) > 2 else None,
                    "rva": f"0x{rva:x}",
                    "file_offset": pos,
                    "file_offset_hex": f"0x{pos:x}",
                    "size_bytes": size,
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "first_16_bytes": blob[:16].hex(),
                })
    walk(0, [])
    leaves.sort(key=lambda r: (str(r["type"]), str(r["name"])))
    return leaves


def dxbc_containers(data: bytes):
    """Parse DXBC containers by header validation, not raw string counting."""
    containers = []
    pos = 0
    covered = 0
    while True:
        pos = data.find(b"DXBC", pos + 1)
        if pos < 0:
            break
        if pos + 32 > len(data):
            break
        total, = struct.unpack_from("<I", data, pos + 24)
        count, = struct.unpack_from("<I", data, pos + 28)
        if not (32 <= total <= len(data) - pos) or not (1 <= count <= 16):
            continue
        # DXBC layout: 32-byte header, then `count` u32 chunk offsets relative
        # to the container start; each chunk is fourcc + u32 size + payload.
        chunks = []
        ok = True
        for i in range(count):
            (rel,) = struct.unpack_from("<I", data, pos + 32 + i * 4)
            if rel + 8 > total:
                ok = False
                break
            fourcc = data[pos + rel:pos + rel + 4].decode("ascii", "replace")
            (size,) = struct.unpack_from("<I", data, pos + rel + 4)
            if rel + 8 + size > total:
                ok = False
                break
            chunks.append({
                "fourcc": fourcc,
                "offset_rel": rel,
                "size": size,
                "file_offset": pos + rel + 8,
            })
        if not ok:
            continue
        if pos < covered:
            continue
        covered = pos + total
        blob = data[pos:pos + total]
        parts = [c["fourcc"] for c in chunks]
        containers.append({
            "file_offset": pos,
            "file_offset_hex": f"0x{pos:x}",
            "size": total,
            "parts": parts,
            "chunks": chunks,
            "dxil_bitcode": any(
                data[c["file_offset"]:c["file_offset"] + 4] == b"BC\xc0\xde"
                for c in chunks),
            "sha256": hashlib.sha256(blob).hexdigest(),
        })
    return containers


def keyword_hits(data: bytes):
    hits = {}
    for kw in KEYWORDS:
        needle = kw.encode()
        rows = []
        for enc, pattern in (("ascii", rb"[\x20-\x7e]{4,}"),
                             ("utf16le", rb"(?:[\x20-\x7e]\x00){4,}")):
            for m in re.finditer(pattern, data):
                try:
                    text = m.group(0).decode("ascii" if enc == "ascii" else "utf-16le")
                except UnicodeDecodeError:
                    continue
                if needle in text.lower().encode():
                    rows.append({"file_offset": m.start(),
                                 "encoding": enc,
                                 "text": text[:200]})
        if rows:
            hits[kw] = rows
    return hits


def entropy_regions(data: bytes, block: int = 65536, threshold: float = 7.4):
    regions = []
    current = None
    for off in range(0, len(data), block):
        chunk = data[off:off + block]
        ent = entropy(chunk)
        if ent >= threshold:
            if current is None:
                current = [off, off + len(chunk), ent, len(chunk)]
            else:
                weighted = current[2] * current[3] + ent * len(chunk)
                current[3] += len(chunk)
                current[2] = weighted / current[3]
                current[1] = off + len(chunk)
        else:
            if current is not None:
                regions.append(current)
                current = None
    if current is not None:
        regions.append(current)
    out = []
    for start, end, ent, size in regions:
        head = data[start:start + 16]
        magic = next((label for sig, label in MAGICS if head.startswith(sig)), None)
        out.append({
            "file_offset": start,
            "file_offset_hex": f"0x{start:x}",
            "size": size,
            "entropy": round(ent, 3),
            "first_16_bytes": head.hex(),
            "magic": magic,
        })
    return out


def build(dll: Path) -> dict:
    data = dll.read_bytes()
    layout = inv._pe_layout(data)
    sections = pe_sections(data)
    image_base = int(sections["image_base"], 16)
    exports = parse_exports(data, image_base)
    imports = inv.parse_imports(data)
    leaves = resource_leaves(data)
    containers = dxbc_containers(data)
    version = inv.parse_versioninfo(data)
    return {
        "artifact": {
            "path": str(dll.resolve()),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "machine": layout["machine"],
            "arch": layout["arch"],
            "bits": layout["bits"],
            "entry_point_rva": sections["entry_point_rva"],
            "image_base": sections["image_base"],
        },
        "sections": sections["sections"],
        "exports": exports,
        "imports": {
            "dll_count": imports["dll_count"],
            "function_count": imports["function_count"],
            "delay_imports": imports["delay_imports"],
            "dlls": [
                {"name": d["name"],
                 "function_count": len(d["functions"]),
                 "functions": [f["name"] if f["name"] is not None
                               else f"ordinal:{f['ordinal']}" for f in d["functions"]]}
                for d in imports["dlls"]
            ],
        },
        "resources": leaves,
        "versioninfo": version,
        "dxbc": {
            "container_count": len(containers),
            "total_bytes": sum(c["size"] for c in containers),
            "containers": containers,
            "raw_dxbc_magic_occurrences": data.count(b"DXBC"),
            "raw_dxil_magic_occurrences": data.count(b"DXIL"),
            "raw_bitcode_magic_occurrences": data.count(b"BC\xc0\xde"),
        },
        "keywords": keyword_hits(data),
        "entropy_regions": entropy_regions(data),
        "method": ("Static-only inventory with Python standard library; the "
                   "input DLL is never loaded or executed."),
        "limitations": [
            "Offsets are file offsets; RVAs are given where a PE mapping is known.",
            "Container part lists and keyword hits are presence evidence only.",
            "High-entropy regions are candidates, not proof of NN weights.",
            "No code was executed; no GPU/Linux behaviour is claimed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = build(args.dll)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
