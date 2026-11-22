#!/usr/bin/env python3
"""Decode AMD AGS "magic UAV" wave-matrix (WMMA) intrinsics in DXIL shaders.

The AGS shader-intrinsics extension encodes each intrinsic as a chain of
`dx.op.atomicCompareExchange` calls on a dummy RawBuffer UAV bound in space
2147420894 (0x7FFF0ADE). Each call carries a packed 32-bit descriptor:

    bits 31..28  magic code       (must be 0x5)
    bits 27..26  unused
    bits 25..24  opcode phase
    bits 23..8   immediate (16 bit, opcode specific)
    bits  7..0   opcode

Encoding taken from dxil-spirv `opcodes/dxil/dxil_ags.hpp`
(is_ags_magic / decode_ags_instruction, AgsUAVMagicRegisterSpace) and the
opcode semantics from `opcodes/dxil/dxil_ags.cpp` (emit_wmma_* functions).

This tool extracts the DXIL part of every shader container, disassembles it with
`llvm-dis`, reassembles the AGS instruction sequences with the same state machine
dxil-spirv uses, and reports opcode/format/shape counts plus per-pass compute
metadata (numthreads, wave size range, groupshared bytes).

Static only: no shader is executed and no GPU is touched.
"""
import argparse
import collections
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fg_shader_census  # noqa: E402
import inspect_fg  # noqa: E402

MAGIC_SPACE = 2147420894
MAGIC_CODE = 0x5

OPCODES = {
    0x01: "Readfirstlane", 0x02: "Readlane", 0x03: "LaneId", 0x04: "Swizzle",
    0x05: "Ballot", 0x06: "MBCnt", 0x07: "Min3U", 0x08: "Min3F", 0x09: "Med3U",
    0x0A: "Med3F", 0x0B: "Max3U", 0x0C: "Max3F", 0x0D: "BaryCoord",
    0x0E: "VtxParam", 0x12: "WaveReduce", 0x13: "WaveScan",
    0x14: "LoadDwAtAddr", 0x17: "DrawIndex", 0x18: "AtomicU64",
    0x19: "GetWaveSize", 0x1A: "BaseInstance", 0x1B: "BaseVertex",
    0x1C: "FloatConversion", 0x1D: "ReadlaneAt", 0x1F: "ShaderClock",
    0x20: "ShaderRealtimeClock", 0x21: "Halt", 0x22: "IntersectBvhNode",
    0x23: "BufferStoreByte", 0x24: "BufferStoreShort", 0x25: "ShaderMarker",
    0x26: "FloatOpWithRoundMode", 0x28: "WaveMatrixMulAcc",
    0x29: "WaveMatrixUavLoad", 0x2A: "WaveMatrixUavStore",
    0x2B: "WaveMatrixGlobalLoad", 0x2C: "WaveMatrixGlobalStore",
    0x2D: "WaveMatrixLdsLoad", 0x2E: "WaveMatrixLdsStore",
    0x2F: "WaveMatrixElementFill", 0x30: "WaveMatrixElementExtract",
    0x31: "WaveMatrixLength", 0x32: "WaveMatrixCopy", 0x33: "WaveMatrixFill",
    0x34: "MatrixSparsityIndexLoad", 0x35: "MatrixElementWiseArithmetic",
    0x36: "Float8Conversion", 0x37: "BuiltIn1", 0x38: "BuiltInArg",
}

# dxil_ags.cpp: switch (impl.ags.num_instructions) per opcode.
EXPECTED_LENGTH = {
    0x28: 21, 0x29: 10, 0x2A: 6, 0x2B: 10, 0x2C: 6, 0x2D: 10, 0x2E: 6,
    0x2F: 13, 0x30: 5, 0x31: 1, 0x32: 13, 0x33: 9, 0x35: 17, 0x36: 1,
}

DATA_FORMATS = {
    0x0: "I4", 0x1: "U4", 0x2: "I8", 0x3: "U8", 0x4: "F16", 0x5: "BF16",
    0x6: "F32", 0x7: "I32", 0x8: "U32", 0x9: "BF8", 0xA: "FP8",
}
MATRIX_TYPES = {0x0: "A", 0x1: "B", 0x2: "Accumulator"}
SHAPES = {0x0: "16x16", 0x1: "32x16", 0x2: "16x32", 0x3: "64x16"}

WMMA_OPS = {
    0x00: "BF16_16X16X16_BF16", 0x01: "F16_16X16X16_F16",
    0x02: "F32_16X16X16_BF16", 0x03: "F32_16X16X16_BF8_BF8",
    0x04: "F32_16X16X16_BF8_FP8", 0x05: "F32_16X16X16_F16",
    0x06: "F32_16X16X16_FP8_BF8", 0x07: "F32_16X16X16_FP8_FP8",
    0x08: "I32_16X16X16_I4", 0x09: "I32_16X16X16_U4", 0x0A: "I32_16X16X16_IU4",
    0x0B: "I32_16X16X16_UI4", 0x0C: "I32_16X16X16_I8", 0x0D: "I32_16X16X16_U8",
    0x0E: "I32_16X16X16_IU8", 0x0F: "I32_16X16X16_UI8",
    0x10: "I32_16X16X32_I4", 0x11: "I32_16X16X32_U4", 0x12: "I32_16X16X32_IU4",
    0x13: "I32_16X16X32_UI4", 0x14: "SWMMA_BF16_16X16X32_BF16",
    0x15: "SWMMA_F16_16X16X32_F16", 0x16: "SWMMA_F32_16X16X32_BF16",
    0x17: "SWMMA_F32_16X16X32_BF8_BF8", 0x18: "SWMMA_F32_16X16X32_BF8_FP8",
    0x19: "SWMMA_F32_16X16X32_F16", 0x1A: "SWMMA_F32_16X16X32_FP8_BF8",
    0x1B: "SWMMA_F32_16X16X32_FP8_FP8", 0x1C: "SWMMA_I32_16X16X32_I4",
    0x1D: "SWMMA_I32_16X16X32_U4", 0x1E: "SWMMA_I32_16X16X32_IU4",
    0x1F: "SWMMA_I32_16X16X32_UI4", 0x20: "SWMMA_I32_16X16X32_I8",
    0x21: "SWMMA_I32_16X16X32_U8", 0x22: "SWMMA_I32_16X16X32_IU8",
    0x23: "SWMMA_I32_16X16X32_UI8", 0x24: "SWMMA_I32_16X16X64_I4",
    0x25: "SWMMA_I32_16X16X64_U4", 0x26: "SWMMA_I32_16X16X64_IU4",
    0x27: "SWMMA_I32_16X16X64_UI4",
}

FLOAT8_CVT = {0x0: "F16_2_FP8", 0x1: "FP8_2_F16", 0x2: "F32_2_FP8",
              0x3: "F32_2_BF8", 0x4: "FP8_2_F32", 0x5: "BF8_2_F32"}

ELEMWISE = {0x1: "add", 0x2: "sub", 0x3: "mul", 0x4: "div", 0x5: "times"}

CREATE_RE = re.compile(
    r"^\s*(%\d+) = call %dx\.types\.Handle @dx\.op\.createHandleFromBinding"
    r"\(i32 217, %dx\.types\.ResBind \{ i32 (-?\d+), i32 (-?\d+), i32 (\d+), i8 (\d+) \}")
ANNOTATE_RE = re.compile(
    r"^\s*(%\d+) = call %dx\.types\.Handle @dx\.op\.annotateHandle"
    r"\(i32 216, %dx\.types\.Handle (%\d+),")
CMPXCHG_RE = re.compile(
    r"^\s*%\d+ = call i\d+ @dx\.op\.atomicCompareExchange\.i\d+\((.*)\)\s*$")
MD_NODE_RE = re.compile(r"^!(\d+) = (.+)$")


def decode_descriptor(value: int) -> dict:
    return {
        "raw": value,
        "magic": (value >> 28) & 0xF,
        "phase": (value >> 24) & 0x3,
        "immediate": (value >> 8) & 0xFFFF,
        "opcode": value & 0xFF,
    }


def decode_modifier(immediate: int) -> dict:
    return {
        "data_format_id": immediate & 0xF,
        "data_format": DATA_FORMATS.get(immediate & 0xF, f"unknown:{immediate & 0xF}"),
        "matrix_type_id": (immediate >> 4) & 0x7,
        "matrix_type": MATRIX_TYPES.get((immediate >> 4) & 0x7, "?"),
        "layout": "column" if (immediate >> 7) & 0x1 else "row",
        "shape_id": (immediate >> 8) & 0x7,
        "shape": SHAPES.get((immediate >> 8) & 0x7, f"unknown:{(immediate >> 8) & 0x7}"),
        "matrix_tile": (immediate >> 11) & 0x1,
    }


ELEMENT_SIZE = {"i8": 1, "i16": 2, "i32": 4, "i64": 8, "half": 2,
                "float": 4, "double": 8, "bfloat": 2}
GROUPSHARED_RE = re.compile(
    r"addrspace\(3\) global (\[(\d+) x (\w+)\]|(\w+))")


def groupshared_bytes(text: str) -> int:
    total = 0
    for match in GROUPSHARED_RE.finditer(text):
        if match.group(2):
            total += int(match.group(2)) * ELEMENT_SIZE.get(match.group(3), 0)
        else:
            total += ELEMENT_SIZE.get(match.group(4), 0)
    return total


def entry_metadata(text: str):
    nodes = {}
    for line in text.splitlines():
        match = MD_NODE_RE.match(line.strip())
        if match:
            nodes[match.group(1)] = match.group(2)
    numthreads = None
    wave = None
    entry = re.search(r"^!dx\.entryPoints = !\{!(\d+)\}", text, re.M)
    if entry:
        node = nodes.get(entry.group(1), "")
        # entry node: {ptr @fn, !"name", ..., !resources, !properties}
        props_ref = re.findall(r"!(\d+)", node)
        props = nodes.get(props_ref[-1], "") if props_ref else ""
        pairs = re.findall(r"i32 (\d+), !(\d+)", props)
        tags = {}
        for tag, ref in pairs:
            tags.setdefault(int(tag), nodes.get(ref, ""))
        if 4 in tags:
            numthreads = [int(v) for v in re.findall(r"i32 (\d+)", tags[4])]
        if 11 in tags:
            wave = [int(v) for v in re.findall(r"i32 (\d+)", tags[11])]
    return numthreads, wave


class Sequence:
    __slots__ = ("insts", "phase")

    def __init__(self):
        self.insts = []
        self.phase = 0


def ags_sequences(text: str):
    """Rebuild AGS sequences with dxil-spirv's push_ags_instruction state machine."""
    magic = set()
    calls = []
    for line in text.splitlines():
        match = CREATE_RE.match(line)
        if match:
            if int(match.group(4)) == MAGIC_SPACE:
                magic.add(match.group(1))
            continue
        match = ANNOTATE_RE.match(line)
        if match and match.group(2) in magic:
            magic.add(match.group(1))
            continue
        match = CMPXCHG_RE.match(line)
        if not match:
            continue
        args = [a.strip() for a in match.group(1).split(", ")]
        if len(args) < 6:
            continue
        handle = args[1].rsplit(" ", 1)[-1]
        if handle not in magic:
            continue
        address = args[2].rsplit(" ", 1)[-1]
        if not address.isdigit():
            continue
        inst = decode_descriptor(int(address))
        data = args[5].rsplit(" ", 1)[-1]
        if data.isdigit():
            inst["data"] = int(data)
        calls.append(inst)

    sequences = []
    current = Sequence()
    for inst in calls:
        if inst["magic"] != MAGIC_CODE:
            continue
        if (not current.insts or inst["phase"] < current.phase
                or inst["opcode"] != current.insts[0]["opcode"]):
            if current.insts:
                sequences.append(current)
            current = Sequence()
        if inst["phase"] in (current.phase, current.phase + 1):
            current.insts.append(inst)
            current.phase = inst["phase"]
    if current.insts:
        sequences.append(current)
    return sequences


def summarise_sequences(sequences):
    counts = collections.Counter()
    mulacc = collections.Counter()
    loads = collections.Counter()
    stores = collections.Counter()
    fills = collections.Counter()
    elemwise = collections.Counter()
    float8 = collections.Counter()
    converts = collections.Counter()
    incomplete = collections.Counter()
    for seq in sequences:
        opcode = seq.insts[0]["opcode"]
        name = OPCODES.get(opcode, f"unknown:0x{opcode:02x}")
        counts[name] += 1
        expected = EXPECTED_LENGTH.get(opcode)
        if expected and len(seq.insts) != expected:
            incomplete[name] += 1
        if opcode == 0x28 and len(seq.insts) > 12:
            code = seq.insts[12]["immediate"] & 0x7F
            mulacc[WMMA_OPS.get(code, f"unknown:0x{code:02x}")] += 1
        elif opcode in (0x29, 0x2B, 0x2D) and len(seq.insts) > 1:
            mod = decode_modifier(seq.insts[1]["immediate"])
            loads[(mod["data_format"], mod["shape"], mod["layout"],
                   mod["matrix_type"])] += 1
        elif opcode in (0x2A, 0x2C, 0x2E) and len(seq.insts) > 5:
            mod = decode_modifier(seq.insts[5]["immediate"])
            stores[(mod["data_format"], mod["shape"], mod["layout"],
                    mod["matrix_type"])] += 1
        elif opcode == 0x33 and seq.insts:
            mod = decode_modifier(seq.insts[0]["immediate"])
            fills[(mod["data_format"], mod["shape"], mod["matrix_type"])] += 1
        elif opcode == 0x2F and len(seq.insts) > 4:
            mod = decode_modifier(seq.insts[4]["immediate"])
            fills[("element", mod["data_format"], mod["shape"])] += 1
        elif opcode == 0x35 and len(seq.insts) > 8:
            mod = decode_modifier(seq.insts[8]["immediate"])
            elemwise[(mod["data_format"], mod["shape"])] += 1
        elif opcode == 0x36 and seq.insts:
            code = seq.insts[0]["immediate"] & 0xFF
            float8[FLOAT8_CVT.get(code, f"unknown:0x{code:02x}")] += 1
        elif opcode == 0x32 and len(seq.insts) > 4:
            src = decode_modifier(seq.insts[4]["immediate"])
            dst = ("%d" % seq.insts[4]["data"]) if "data" in seq.insts[4] else "-"
            if "data" in seq.insts[4]:
                dst = decode_modifier(seq.insts[4]["data"])["data_format"]
            converts[(src["data_format"], dst)] += 1
    return {
        "opcode_counts": dict(counts),
        "converts": {"|".join(k): v for k, v in converts.items()},
        "incomplete_sequences": dict(incomplete),
        "mulacc_opcodes": dict(mulacc),
        "loads": {"|".join(k): v for k, v in loads.items()},
        "stores": {"|".join(k): v for k, v in stores.items()},
        "fills": {"|".join(k): v for k, v in fills.items()},
        "elementwise": {"|".join(k): v for k, v in elemwise.items()},
        "float8_conversions": dict(float8),
        "converts": {"|".join(k): v for k, v in converts.items()},
    }


def census(dll: Path, llvm_dis: str, workdir: Path):
    data = dll.read_bytes()
    containers = inspect_fg.dxbc_containers(data)
    workdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for container in containers:
        dxil = next((c for c in container["chunks"] if c["fourcc"] == "DXIL"), None)
        if dxil is None:
            continue
        blob = data[dxil["file_offset"]:dxil["file_offset"] + dxil["size"]]
        start = blob.find(b"BC\xc0\xde")
        if start < 0:
            continue
        names = [k["name"] for k in
                 fg_shader_census.kernel_names(data, container["file_offset"], container["size"])]
        name = next((n for n in names if n.startswith("mlfi")),
                    names[0] if names else None)
        stem = f"{container['file_offset']:08x}"
        bc = workdir / f"{stem}.bc"
        ir = workdir / f"{stem}.ll"
        bc.write_bytes(blob[start:])
        proc = subprocess.run([llvm_dis, str(bc), "-o", str(ir)],
                              capture_output=True, check=False)
        if proc.returncode != 0:
            rows.append({"container_offset": container["file_offset"], "error": "llvm-dis failed"})
            continue
        text = ir.read_text(errors="replace")
        numthreads, wave = entry_metadata(text)
        summary = summarise_sequences(ags_sequences(text))
        rows.append({
            "container_offset": container["file_offset"],
            "container_offset_hex": container["file_offset_hex"],
            "container_size": container["size"],
            "dxil_chunk_offset": dxil["file_offset"],
            "name": name,
            "family": ("non_mlfi" if not name else name.rsplit("_pass", 1)[0]),
            "numthreads": numthreads,
            "wave_size_range": wave,
            "groupshared_bytes": groupshared_bytes(text),
            "uses_magic_uav": bool(summary["opcode_counts"]),
            "ags": summary,
        })
    return rows


def aggregate(rows) -> dict:
    totals = collections.Counter()
    mulacc = collections.Counter()
    loads = collections.Counter()
    stores = collections.Counter()
    fills = collections.Counter()
    elemwise = collections.Counter()
    float8 = collections.Counter()
    converts = collections.Counter()
    threads = collections.Counter()
    waves = collections.Counter()
    tgsm = []
    passes_with_wmma = 0
    for row in rows:
        if "error" in row:
            continue
        if row["uses_magic_uav"]:
            passes_with_wmma += 1
        totals.update(row["ags"]["opcode_counts"])
        mulacc.update(row["ags"]["mulacc_opcodes"])
        loads.update(row["ags"]["loads"])
        stores.update(row["ags"]["stores"])
        fills.update(row["ags"]["fills"])
        elemwise.update(row["ags"]["elementwise"])
        float8.update(row["ags"]["float8_conversions"])
        converts.update(row["ags"].get("converts", {}))
        if row["numthreads"]:
            threads["x".join(str(v) for v in row["numthreads"])] += 1
        waves["x".join(str(v) for v in row["wave_size_range"]) if row["wave_size_range"] else "none"] += 1
        tgsm.append(row["groupshared_bytes"])
    tgsm.sort()
    return {
        "passes": len([r for r in rows if "error" not in r]),
        "passes_with_magic_uav": passes_with_wmma,
        "opcode_counts": dict(totals),
        "mulacc_opcodes": dict(mulacc),
        "loads": dict(loads),
        "stores": dict(stores),
        "fills": dict(fills),
        "elementwise": dict(elemwise),
        "float8_conversions": dict(float8),
        "converts": dict(converts),
        "numthreads": dict(threads),
        "wave_size_range": dict(waves),
        "groupshared_bytes": {
            "max": tgsm[-1] if tgsm else 0,
            "median": tgsm[len(tgsm) // 2] if tgsm else 0,
            "nonzero_passes": sum(1 for v in tgsm if v),
            "histogram": dict(collections.Counter(tgsm)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--llvm-dis", default=shutil.which("llvm-dis") or "llvm-dis")
    parser.add_argument("--workdir", type=Path, default=None)
    args = parser.parse_args()
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="ags-wmma-"))
    rows = census(args.dll, args.llvm_dis, workdir)
    report = {
        "artifact": {"path": str(args.dll.resolve()),
                     "sha256": inspect_fg.hashlib.sha256(args.dll.read_bytes()).hexdigest()},
        "magic_uav_space": MAGIC_SPACE,
        "encoding": "dxil-spirv opcodes/dxil/dxil_ags.hpp decode_ags_instruction",
        "passes": rows,
        "aggregate": aggregate(rows),
        "aggregate_4k": aggregate([r for r in rows if r.get("family") == "mlfi_4k"]),
        "aggregate_8k": aggregate([r for r in rows if r.get("family") == "mlfi_8k"]),
        "aggregate_non_mlfi": aggregate([r for r in rows if r.get("family") == "non_mlfi"]),
        "limitations": [
            "Counts are static instruction sequences in DXIL, not executed dispatches.",
            "Formats/shapes come from the AGS modifier immediates decoded as in dxil-spirv.",
            "No claim about runtime support, driver behaviour or GPU results.",
        ],
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
