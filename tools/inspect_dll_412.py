#!/usr/bin/env python3
"""Inventario estatico completo de la DLL 4.1.2 (XMX) sin cargarla ni ejecutarla.

Extiende tools/inspect_dll.py sin modificarlo: reutiliza su funcion inspect()
para las claves originales (path, size_bytes, sha256, intel_api_strings,
evidence_strings, limitations) y anade exports, imports, recursos PE con
hashes, VERSIONINFO/manifiesto y cadenas de version/modelo.

Solo biblioteca estandar. No ejecuta la DLL, no toca GPU/Wine ni prefijos.
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import inspect_dll  # noqa: E402
import extract_resources  # noqa: E402


def _unpack(data: bytes, fmt: str, offset: int):
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError("Truncated PE structure")
    return struct.unpack_from(fmt, data, offset)


def _collect_strings(data: bytes) -> set:
    strings = set()
    for encoding, pattern in (
        ("ascii", rb"[\x20-\x7e]{6,}"),
        ("utf-16le", rb"(?:[\x20-\x7e]\x00){6,}"),
    ):
        for match in re.findall(pattern, data):
            try:
                strings.add(match.decode(encoding))
            except UnicodeDecodeError:
                continue
    return strings


def _pe_layout(data: bytes):
    if data[:2] != b"MZ":
        raise ValueError("Not an MZ/PE candidate")
    (pe_offset,) = _unpack(data, "<I", 0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("Missing PE signature")
    coff = pe_offset + 4
    (machine,) = _unpack(data, "<H", coff)
    (num_sections,) = _unpack(data, "<H", coff + 2)
    (opt_size,) = _unpack(data, "<H", coff + 16)
    opt = coff + 20
    (magic,) = _unpack(data, "<H", opt)
    if magic not in (0x10B, 0x20B):
        raise ValueError("Unsupported optional header")
    is_plus = magic == 0x20B
    directory_base = opt + (112 if is_plus else 96)
    sections = []
    for n in range(num_sections):
        off = opt + opt_size + 40 * n
        vsize, va, rawsize, raw = _unpack(data, "<IIII", off + 8)
        sections.append((va, vsize, rawsize, raw))

    def rva_to_offset(rva: int, size: int = 1) -> int:
        for va, vsize, rawsize, raw in sections:
            if va <= rva < va + max(vsize, rawsize):
                if rva - va + size <= rawsize:
                    pos = raw + (rva - va)
                    if pos + size <= len(data):
                        return pos
        raise ValueError(f"Unmapped RVA: {rva:#x}")

    def data_directory(index: int):
        rva, size = _unpack(data, "<II", directory_base + index * 8)
        return rva, size

    bits = 64 if is_plus else 32
    arch = "x86_64" if machine == 0x8664 else f"machine:{machine:#x}"
    return {
        "machine": machine,
        "arch": arch,
        "bits": bits,
        "is_plus": is_plus,
        "num_sections": num_sections,
        "rva_to_offset": rva_to_offset,
        "data_directory": data_directory,
    }


def parse_exports(data: bytes):
    layout = _pe_layout(data)
    rva, size = layout["data_directory"](0)
    if not rva:
        return []
    off = layout["rva_to_offset"](rva, 40)
    (
        _chars,
        _ts,
        _vmaj,
        _vmin,
        _name_rva,
        base,
        nfunc,
        nname,
        addr_func,
        addr_names,
        addr_ord,
    ) = _unpack(data, "<IIHHIIIIIII", off)
    exports = []
    for i in range(nname):
        (name_rva,) = _unpack(data, "<I", layout["rva_to_offset"](addr_names + i * 4, 4))
        name_off = layout["rva_to_offset"](name_rva, 8)
        end = data.find(b"\x00", name_off)
        name = data[name_off:end].decode("ascii")
        (ordinal_index,) = _unpack(data, "<H", layout["rva_to_offset"](addr_ord + i * 2, 2))
        (func_rva,) = _unpack(
            data, "<I", layout["rva_to_offset"](addr_func + ordinal_index * 4, 4)
        )
        exports.append(
            {
                "ordinal": base + ordinal_index,
                "name": name,
                "rva": func_rva,
                "address": f"0x180000000+{func_rva:#x}"
                if False
                else hex(0x180000000 + func_rva),
            }
        )
    exports.sort(key=lambda e: e["ordinal"])
    return exports


def parse_imports(data: bytes):
    layout = _pe_layout(data)
    rva, _size = layout["data_directory"](1)
    delay_rva, _delay_size = layout["data_directory"](13)
    if not rva:
        return {"dll_count": 0, "function_count": 0, "delay_imports": 0, "dlls": []}
    dlls = []
    total = 0
    index = 0
    is_plus = layout["is_plus"]
    entry_size = 8 if is_plus else 4
    while True:
        desc_off = layout["rva_to_offset"](rva + index * 20, 20)
        ilt, _ts, _fwd, name_rva, _iat = _unpack(data, "<IIIII", desc_off)
        if (ilt, _ts, _fwd, name_rva, _iat) == (0, 0, 0, 0, 0):
            break
        name_off = layout["rva_to_offset"](name_rva, 8)
        end = data.find(b"\x00", name_off)
        dll_name = data[name_off:end].decode("ascii", errors="replace")
        functions = []
        j = 0
        while True:
            thunk_off = layout["rva_to_offset"](ilt + j * entry_size, entry_size)
            entry = _unpack(data, "<Q" if is_plus else "<I", thunk_off)[0]
            if entry == 0:
                break
            is_ordinal = (entry >> 63) & 1 if is_plus else (entry >> 31) & 1
            if is_ordinal:
                functions.append({"ordinal": entry & 0xFFFF, "name": None, "hint": None})
            else:
                hint_rva = entry & 0x7FFFFFFF
                hint_off = layout["rva_to_offset"](hint_rva, 4)
                (hint,) = _unpack(data, "<H", hint_off)
                end2 = data.find(b"\x00", hint_off + 2)
                fname = data[hint_off + 2 : end2].decode("ascii", errors="replace")
                functions.append({"hint": hint, "name": fname, "ordinal": None})
            j += 1
            if j > 4096:
                raise ValueError("Import table too large")
        dlls.append({"name": dll_name, "functions": functions})
        total += len(functions)
        index += 1
        if index > 256:
            raise ValueError("Too many import DLLs")
    return {
        "dll_count": len(dlls),
        "function_count": total,
        "delay_imports": 0 if not delay_rva else -1,
        "dlls": dlls,
    }


def parse_resources(data: bytes):
    leaves = extract_resources.extract(data)
    resources = []
    for path, blob in leaves:
        resources.append(
            {
                "type": path[0] if len(path) > 0 else None,
                "name": path[1] if len(path) > 1 else None,
                "language": path[2] if len(path) > 2 else None,
                "size_bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
            }
        )
    resources.sort(key=lambda r: (r["type"], r["name"]))
    return resources


def parse_versioninfo(data: bytes):
    for path, blob in extract_resources.extract(data):
        if len(path) == 3 and path[0] == 16:
            text = blob.decode("utf-16le", errors="replace")
            parts = [p for p in text.split("\x00") if p.strip() != ""]
            fields = {}
            for key in (
                "CompanyName",
                "FileDescription",
                "FileVersion",
                "LegalCopyright",
                "ProductName",
                "ProductVersion",
            ):
                for i, part in enumerate(parts):
                    if key in part and i + 1 < len(parts):
                        fields[key] = parts[i + 1].strip()
                        break
            fields["raw_sha256"] = hashlib.sha256(blob).hexdigest()
            fields["size_bytes"] = len(blob)
            return fields
    return {}


def parse_manifest(data: bytes):
    for path, blob in extract_resources.extract(data):
        if len(path) == 3 and path[0] == 24:
            try:
                text = blob.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            return {
                "size_bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "text": text,
            }
    return {}


def collect_model_strings(strings: set) -> dict:
    def containing(needle: str):
        return sorted(s for s in strings if needle in s)

    def containing_fold(needle: str):
        low = needle.lower()
        return sorted(s for s in strings if low in s.lower())

    passes = set()
    for s in strings:
        for match in re.finditer(r"pass(\d+)", s):
            try:
                passes.add(int(match.group(1)))
            except ValueError:
                continue
    model_402x = sorted(s for s in strings if "4.0.2X" in s)
    model_412x = sorted(s for s in strings if "4.1.2X" in s)
    return {
        "model_4_0_2X": model_402x,
        "model_4_1_2X": model_412x,
        "lite_markers": sorted(s for s in strings if "Lite" in s)[:40],
        "int8_markers": sorted(s for s in strings if "INT8" in s),
        "dg2_markers": [s for s in containing("DG2") if len(s) < 120][:20],
        "xe2_markers": [s for s in containing("Xe2") if len(s) < 120][:20],
        "dlss_markers_count": len(containing_fold("dlss")),
        "has_opti_plugin_init": "OptiPluginInit" in strings,
        "has_create_device_extension_context2": "CreateDeviceExtensionContext2" in strings,
        "has_get_cached_blob": "INTC_D3D12_GetCachedBlob" in strings,
        "context_requested": "4.20.0" if any("4.20.0" in s for s in strings) else None,
        "diag_abi_markers": sorted(s for s in strings if "DIAG" in s or "0028ZR" in s),
        "passes_found": sorted(passes),
    }


def build_report(dll: Path) -> dict:
    data = dll.read_bytes()
    base = inspect_dll.inspect(dll)
    exports = parse_exports(data)
    imports = parse_imports(data)
    resources = parse_resources(data)
    versioninfo = parse_versioninfo(data)
    manifest = parse_manifest(data)
    strings = _collect_strings(data)
    models = collect_model_strings(strings)
    layout = _pe_layout(data)
    return {
        "artifact": {
            "path": str(dll.resolve()),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "machine": layout["machine"],
            "arch": layout["arch"],
            "bits": layout["bits"],
        },
        "intel_api_strings": base["intel_api_strings"],
        "evidence_strings": base["evidence_strings"],
        "exports": exports,
        "imports": {
            "dll_count": imports["dll_count"],
            "function_count": imports["function_count"],
            "delay_imports": imports["delay_imports"],
            "dlls": [
                {
                    "name": d["name"],
                    "function_count": len(d["functions"]),
                    "ordinals": sorted(
                        f["ordinal"] for f in d["functions"] if f["ordinal"] is not None
                    ),
                    "functions": [
                        f["name"] if f["name"] is not None else f"ordinal:{f['ordinal']}"
                        for f in d["functions"]
                    ],
                }
                for d in imports["dlls"]
            ],
        },
        "resources": resources,
        "versioninfo": versioninfo,
        "manifest": manifest,
        "model_strings": models,
        "method": (
            "Static-only inventory with Python standard library; "
            "the input DLL is never loaded or executed."
        ),
        "limitations": base["limitations"]
        + [
            "Import/export/resource rows reproduce PE tables; they do not prove runtime loading or API success.",
            "Model/version strings are presence markers only; they do not prove GPU correctness or Linux compatibility.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = build_report(args.dll)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
