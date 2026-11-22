#!/usr/bin/env python3
"""Semantic map of the FSR ML-frame-generation (mlfi) compute passes.

For every `mlfi_4k_passN` shader in an AMD FidelityFX frame-generation DLL this
tool produces one row: bindings (register/space/class, read/write), AGS wave-matrix
intrinsics (opcode, tile format, layout, byte offset/stride), non-AGS instruction
mix, texture traffic, barriers, compute limits, a code-template id and a coarse
layer classification.

It also diffs 4k against 8k (normalized-IR equality plus literal deltas) and
derives a buffer-offset data flow: an AGS `WaveMatrixUavStore` base offset is
matched against the AGS load base offsets of every other pass.

Everything is static: DXIL is extracted from the PE and disassembled with
`llvm-dis`; nothing is executed and no GPU is touched.
"""
import argparse
import collections
import hashlib
import json
import re
import shutil
import struct
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
RESOURCE_CLASS = {0: "SRV", 1: "UAV", 2: "CBV", 3: "Sampler"}
DATA_FORMATS = {
    0x0: "I4", 0x1: "U4", 0x2: "I8", 0x3: "U8", 0x4: "F16", 0x5: "BF16",
    0x6: "F32", 0x7: "I32", 0x8: "U32", 0x9: "BF8", 0xA: "FP8",
}
MATRIX_TYPES = {0x0: "A", 0x1: "B", 0x2: "Accumulator"}
WMMA_OPS = {
    0x00: "BF16_16X16X16_BF16", 0x01: "F16_16X16X16_F16",
    0x02: "F32_16X16X16_BF16", 0x03: "F32_16X16X16_BF8_BF8",
    0x04: "F32_16X16X16_BF8_FP8", 0x05: "F32_16X16X16_F16",
    0x06: "F32_16X16X16_FP8_BF8", 0x07: "F32_16X16X16_FP8_FP8",
    0x08: "I32_16X16X16_I4", 0x09: "I32_16X16X16_U4", 0x0A: "I32_16X16X16_IU4",
    0x0B: "I32_16X16X16_UI4", 0x0C: "I32_16X16X16_I8", 0x0D: "I32_16X16X16_U8",
    0x0E: "I32_16X16X16_IU8", 0x0F: "I32_16X16X16_UI8",
}
EXPECTED_LEN = {0x28: 21, 0x29: 10, 0x2A: 6, 0x2B: 10, 0x2C: 6, 0x2D: 10,
                0x2E: 6, 0x2F: 13, 0x30: 5, 0x31: 1, 0x32: 13, 0x33: 9,
                0x35: 17, 0x36: 1}
AGS_OPS = {
    0x28: "MulAcc", 0x29: "UavLoad", 0x2A: "UavStore", 0x2B: "GlobalLoad",
    0x2C: "GlobalStore", 0x2D: "LdsLoad", 0x2E: "LdsStore",
    0x2F: "ElementFill", 0x30: "ElementExtract", 0x31: "Length",
    0x32: "Copy", 0x33: "Fill", 0x35: "ElementWise", 0x36: "Float8Conversion",
}
ALU_RE = re.compile(
    r"^\s*(?:%\S+ = (?:tail )?)?(fadd|fsub|fmul|fdiv|frem|fneg|"
    r"sitofp|uitofp|fptosi|fptoui|fpext|fptrunc|"
    r"icmp|fcmp|select|phi|br|call|load|store|getelementptr|bitcast|"
    r"zext|sext|trunc|shl|lshr|ashr|and|or|xor|alloca|extractvalue|"
    r"insertvalue|atomicrmw|cmpxchg|sdiv|udiv|srem|urem)\b", re.M)
CREATE_RE = re.compile(
    r"(%\d+) = call %dx\.types\.Handle @dx\.op\.createHandleFromBinding"
    r"\(i32 217, %dx\.types\.ResBind \{ i32 (-?\d+), i32 (-?\d+), i32 (\d+), i8 (\d+) \}")
ANNOTATE_RE = re.compile(
    r"(%\d+) = call %dx\.types\.Handle @dx\.op\.annotateHandle"
    r"\(i32 216, %dx\.types\.Handle (%\d+), %dx\.types\.ResourceProperties \{ i32 (\d+), i32 (\d+) \}")
CMPXCHG_RE = re.compile(
    r"atomicCompareExchange\.i\d+\(i32 79, %dx\.types\.Handle %(\d+), i32 (\d+), "
    r"i32 undef, i32 undef, i32 (%\d+|\d+), i32 (%\d+|\d+)\)")
HANDLE_OP_RE = re.compile(r"@dx\.op\.([A-Za-z0-9]+)\.?[a-z0-9]*\(i32 \d+, %dx\.types\.Handle %(\d+)")
DEF_RE = re.compile(r"^\s*(%\d+) = (.+)$")
GSHARED_RE = re.compile(r"addrspace\(3\) global (\[(\d+) x (\w+)\]|(\w+))")
ELEM_SIZE = {"i8": 1, "i16": 2, "i32": 4, "i64": 8, "half": 2,
             "float": 4, "double": 8, "bfloat": 2}


def normalize_ir(text: str) -> str:
    """IR with pass name, SSA names, metadata ids and integer literals erased."""
    out = []
    started = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("define"):
            started = True
        if not started or not stripped or stripped.startswith(";"):
            continue
        stripped = re.sub(r"mlfi_[0-9a-z_]+", "KERNEL", stripped)
        stripped = re.sub(r"!\d+", "!m", stripped)
        stripped = re.sub(r"![A-Za-z0-9_.$]+", "!m", stripped)
        stripped = re.sub(r"%\d+", "%s", stripped)
        stripped = re.sub(r'%"[^"]*"', "%s", stripped)
        stripped = re.sub(r"(?<![\w%])-?\d+(\.\d+)?(e[-+]?\d+)?(?![\w%])", "0", stripped)
        stripped = re.sub(r"\s+", " ", stripped)
        out.append(stripped)
    return "\n".join(out)


def groupshared_bytes(text: str) -> int:
    total = 0
    for match in GSHARED_RE.finditer(text):
        if match.group(2):
            total += int(match.group(2)) * ELEM_SIZE.get(match.group(3), 0)
        else:
            total += ELEM_SIZE.get(match.group(4), 0)
    return total


def entry_metadata(text: str):
    nodes = {}
    for line in text.splitlines():
        match = re.match(r"^!(\d+) = (.+)$", line.strip())
        if match:
            nodes[match.group(1)] = match.group(2)
    numthreads = wave = None
    entry = re.search(r"^!dx\.entryPoints = !\{!(\d+)\}", text, re.M)
    if entry:
        node = nodes.get(entry.group(1), "")
        refs = re.findall(r"!(\d+)", node)
        props = nodes.get(refs[-1], "") if refs else ""
        tags = {}
        for tag, ref in re.findall(r"i32 (\d+), !(\d+)", props):
            tags.setdefault(int(tag), nodes.get(ref, ""))
        if 4 in tags:
            numthreads = [int(v) for v in re.findall(r"i32 (\d+)", tags[4])]
        if 11 in tags:
            wave = [int(v) for v in re.findall(r"i32 (\d+)", tags[11])]
    return numthreads, wave


def parse_pass(text: str) -> dict:
    defs = {}
    for line in text.splitlines():
        match = DEF_RE.match(line)
        if match:
            defs[match.group(1)] = match.group(2)

    def constant_of(value: str, depth: int = 3):
        """Largest plausible byte offset in the definition chain of `value`."""
        if value.isdigit():
            return int(value)
        expr = defs.get(value, "")
        if not expr:
            return None
        add = re.search(r"add i32 .*?, (-?\d+)$", expr) or re.search(r"add i32 (-?\d+),", expr)
        if add:
            return int(add.group(1))
        if depth > 0:
            for ref in re.findall(r"%\d+", expr):
                found = constant_of(ref, depth - 1)
                if found:
                    return found
        numbers = [int(n) for n in re.findall(r"(?<![\w%])-?\d+", expr) if 4096 <= int(n) < (1 << 28)]
        return max(numbers) if numbers else None

    bindings = {}
    for match in CREATE_RE.finditer(text):
        bindings[match.group(1)] = {
            "register": int(match.group(2)), "upper": int(match.group(3)),
            "space": int(match.group(4)), "kind": int(match.group(5)),
        }
    for match in re.finditer(
            r"(%\d+) = call %dx\.types\.Handle @dx\.op\.createHandleFromBinding"
            r"\(i32 217, %dx\.types\.ResBind zeroinitializer", text):
        bindings[match.group(1)] = {"register": 0, "upper": 0, "space": 0, "kind": 0,
                                    "implicit": True}
    roots = {}
    for match in ANNOTATE_RE.finditer(text):
        src = match.group(2)
        while src in roots:
            src = roots[src]
        roots[match.group(1)] = src

    usage = collections.Counter()
    for match in HANDLE_OP_RE.finditer(text):
        root = roots.get("%" + match.group(2), "%" + match.group(2))
        usage[(root, match.group(1))] += 1

    # AGS sequences: same state machine as dxil-spirv push_ags_instruction.
    sequences = []
    current = None
    for match in CMPXCHG_RE.finditer(text):
        address = int(match.group(2))
        value = match.group(3)
        stride = int(match.group(4)) if match.group(4).isdigit() else None
        opcode = address & 0xFF
        phase = (address >> 24) & 0x3
        immediate = (address >> 8) & 0xFFFF
        if (current is None or phase < current["phase"] or opcode != current["op"]):
            if current:
                sequences.append(current)
            current = {"op": opcode, "phase": phase, "n": 0,
                       "offset": constant_of(value), "stride": stride, "imms": []}
        if phase in (current["phase"], current["phase"] + 1):
            current["imms"].append(immediate)
            current["n"] += 1
            current["phase"] = phase
            # dxil-spirv flushes a chain as soon as it holds the expected number
            # of instructions; long chains (MulAcc) never bump the phase field.
            if current["n"] >= EXPECTED_LEN.get(current["op"], 1 << 30):
                sequences.append(current)
                current = None
    if current:
        sequences.append(current)

    ags = collections.Counter()
    mulacc = collections.Counter()
    loads = collections.Counter()
    stores = collections.Counter()
    converts = collections.Counter()
    a_offsets, b_offsets, out_offsets = set(), set(), set()
    def imm_at(seq, index):
        imms = seq["imms"]
        return imms[index] if len(imms) > index else 0

    for seq in sequences:
        op = seq["op"]
        ags[AGS_OPS.get(op, f"0x{op:02x}")] += 1
        offset = seq["offset"] if seq["offset"] and 0 < seq["offset"] < (1 << 26) else None
        if op == 0x28:
            mulacc[WMMA_OPS.get(imm_at(seq, 12) & 0x7F,
                                f"0x{imm_at(seq, 12) & 0x7F:02x}")] += 1
        elif op in (0x29, 0x2B):
            mod = imm_at(seq, 1)
            fmt = DATA_FORMATS.get(mod & 0xF, "?")
            layout = "col" if (mod >> 7) & 1 else "row"
            kind = MATRIX_TYPES.get((mod >> 4) & 0x7, "?")
            loads[f"{fmt}|{layout}|{kind}"] += 1
            if offset:
                (a_offsets if kind == "A" else b_offsets).add(offset)
        elif op in (0x2A, 0x2C):
            mod = imm_at(seq, 5)
            stores[DATA_FORMATS.get(mod & 0xF, "?")] += 1
            if offset:
                out_offsets.add(offset)
        elif op == 0x32:
            converts[DATA_FORMATS.get(imm_at(seq, 4) & 0xF, "?")] += 1

    alu = collections.Counter(m.group(1) for m in ALU_RE.finditer(text))
    unary = collections.Counter()
    for match in re.finditer(r"@dx\.op\.unary\.([a-z0-9]+)\(i32 (\d+)", text):
        unary[f"{match.group(1)}:{match.group(2)}"] += 1
    binary = collections.Counter()
    for match in re.finditer(r"@dx\.op\.binary\.([a-z0-9]+)\(i32 (\d+)", text):
        binary[f"{match.group(1)}:{match.group(2)}"] += 1

    resources = {}
    for root, info in bindings.items():
        ops = {op: count for (r, op), count in usage.items() if r == root}
        if not ops:
            continue
        kind = "AGS-magic" if info["space"] == MAGIC_SPACE else RESOURCE_CLASS.get(info["kind"], "?")
        reads = sum(v for k, v in ops.items() if k in (
            "rawBufferLoad", "textureLoad", "textureGather", "sampleLevel", "sample",
            "sampleBias", "sampleCmp", "cbufferLoadLegacy", "cbufferLoad"))
        writes = sum(v for k, v in ops.items() if k in (
            "rawBufferStore", "textureStore", "bufferStore"))
        resources[root] = {
            "class": kind, "register": info["register"], "space": info["space"],
            "implicit": info.get("implicit", False),
            "ops": ops, "reads": reads, "writes": writes,
        }

    return {
        "numthreads": entry_metadata(text)[0],
        "wave_size_range": entry_metadata(text)[1],
        "groupshared_bytes": groupshared_bytes(text),
        "resources": resources,
        "ags": dict(ags),
        "mulacc": dict(mulacc),
        "loads": dict(loads),
        "stores": dict(stores),
        "converts": dict(converts),
        "alu": dict(alu),
        "unary": dict(unary),
        "binary": dict(binary),
        "samples": sum(usage[(r, op)] for (r, op) in usage
                       if op in ("sampleLevel", "sample", "sampleBias")),
        "texture_loads": sum(usage[(r, op)] for (r, op) in usage if op == "textureLoad"),
        "texture_gathers": sum(usage[(r, op)] for (r, op) in usage if op == "textureGather"),
        "barriers": sum(usage[(r, op)] for (r, op) in usage if op == "barrier"),
        "atomic_rmw": alu.get("atomicrmw", 0),
        "loops": len(set(re.findall(r"!llvm\.loop !(\d+)", text))),
        "a_offsets": sorted(a_offsets),
        "b_offsets": sorted(b_offsets),
        "out_offsets": sorted(out_offsets),
    }


def classify(row: dict) -> tuple:
    mulacc = row["mulacc"]
    total_mul = sum(mulacc.values())
    fp8 = sum(v for k, v in mulacc.items() if "FP8" in k)
    epilogue = any(row["ags"].get(k) for k in ("ElementWise", "ElementFill",
                                               "ElementExtract", "Fill", "Copy"))
    if total_mul:
        label = "matmul_fp8" if fp8 == total_mul else ("matmul_fp8+f16" if fp8 else "matmul_f16")
        if epilogue:
            label += "+epilogue"
        return label, f"MulAcc={total_mul} (fp8={fp8}), epilogue ops={epilogue}"
    if row["samples"] or row["texture_gathers"]:
        return "texture_resample", f"sample={row['samples']} gather={row['texture_gathers']}"
    if row["texture_loads"]:
        return "texture_load_convert", f"textureLoad={row['texture_loads']}"
    if row["groupshared_bytes"] and row["barriers"]:
        return "reduce_or_pool", f"TGSM={row['groupshared_bytes']} barriers={row['barriers']}"
    if row["unary"]:
        return "unary_activation", f"unary ops={sum(row['unary'].values())}"
    if row["alu"].get("fadd", 0) + row["alu"].get("fmul", 0) > 4:
        return "elementwise", f"fadd={row['alu'].get('fadd')} fmul={row['alu'].get('fmul')}"
    if row["atomic_rmw"]:
        return "atomic_scatter", f"atomicrmw={row['atomic_rmw']}"
    def data_ops(keys):
        return sum(r["ops"].get(k, 0) for r in row["resources"].values() for k in keys)

    writes = data_ops(("rawBufferStore", "textureStore", "bufferStore"))
    reads = data_ops(("rawBufferLoad", "textureLoad", "textureGather", "sample",
                      "sampleLevel", "sampleBias"))
    if writes and not reads:
        return "param_store", f"store-only: {writes} writes, 0 reads, no math"
    if reads and not writes:
        return "param_load", f"read-only: {reads} reads, 0 writes"
    return "io_or_pack", "no matmul/texture/unary traffic"


def build(dll: Path, llvm_dis: str, workdir: Path) -> dict:
    data = dll.read_bytes()
    containers = inspect_fg.dxbc_containers(data)
    workdir.mkdir(parents=True, exist_ok=True)
    passes = {}
    for container in containers:
        dxil = next((c for c in container["chunks"] if c["fourcc"] == "DXIL"), None)
        if dxil is None:
            continue
        names = [k["name"] for k in fg_shader_census.kernel_names(
            data, container["file_offset"], container["size"])]
        name = next((n for n in names if n.startswith("mlfi_")), None)
        if not name:
            continue
        blob = data[dxil["file_offset"]:dxil["file_offset"] + dxil["size"]]
        start = blob.find(b"BC\xc0\xde")
        if start < 0:
            continue
        stem = f"{container['file_offset']:08x}"
        bc, ir = workdir / f"{stem}.bc", workdir / f"{stem}.ll"
        bc.write_bytes(blob[start:])
        if not ir.exists():
            proc = subprocess.run([llvm_dis, str(bc), "-o", str(ir)],
                                  capture_output=True, check=False)
            if proc.returncode != 0:
                continue
        text = ir.read_text(errors="replace")
        variant, index = name.split("_pass")
        variant = variant.replace("mlfi_", "")
        row = parse_pass(text)
        row.update({
            "name": name, "variant": variant, "index": int(index),
            "container_offset": container["file_offset"],
            "container_offset_hex": container["file_offset_hex"],
            "container_size": container["size"],
            "dxil_chunk_offset": dxil["file_offset"],
            "dxil_size": dxil["size"],
            "template": hashlib.sha256(normalize_ir(text).encode()).hexdigest()[:12],
            "literals": [int(x) for x in re.findall(
                r"(?<![\w.])-?\d+(?![\w.])", text.split("define", 1)[1].split("\n}", 1)[0])
                if x not in ("0",)][:4000],
        })
        passes[name] = row

    rows = [passes[n] for n in sorted(passes, key=lambda s: (s.split("_")[1], int(s.split("_pass")[1])))]
    for row in rows:
        label, why = classify(row)
        row["layer_class"] = label
        row["layer_evidence"] = why

    # 4k vs 8k
    pairs = []
    for row in rows:
        if row["variant"] != "4k":
            continue
        twin = passes.get(f"mlfi_8k_pass{row['index']}")
        if not twin:
            continue
        same_code = row["template"] == twin["template"]
        diffs = [(a, b) for a, b in zip(row["literals"], twin["literals"]) if a != b]
        pairs.append({
            "pass": row["index"], "same_code_modulo_constants": same_code,
            "size_delta_bytes": twin["container_size"] - row["container_size"],
            "literal_delta_count": len(diffs),
            "literal_deltas_sample": diffs[:6],
        })

    # templates over the 4k variant
    templates = collections.defaultdict(list)
    for row in rows:
        if row["variant"] == "4k":
            templates[row["template"]].append(row)

    # static (weight-like) offsets: identical in 4k and 8k
    static, dynamic = set(), set()
    for row in rows:
        if row["variant"] != "4k":
            continue
        twin = passes.get(f"mlfi_8k_pass{row['index']}")
        mine = set(row["a_offsets"]) | set(row["b_offsets"])
        other = set(twin["a_offsets"]) | set(twin["b_offsets"]) if twin else set()
        static |= mine & other
        dynamic |= mine - other

    # data flow: store offset of one pass vs load offsets of another
    flow = []
    out_by_pass = {row["index"]: [o for o in row["out_offsets"] if o >= 4096]
                   for row in rows if row["variant"] == "4k"}
    for dst in rows:
        if dst["variant"] != "4k":
            continue
        reads = {o for o in (set(dst["a_offsets"]) | set(dst["b_offsets"])) if o >= 4096}
        for src_pass, offsets in out_by_pass.items():
            if src_pass >= dst["index"]:
                continue
            common = reads & set(offsets)
            if common:
                flow.append({"from_pass": src_pass, "to_pass": dst["index"],
                             "offset": max(common)})

    histogram = collections.Counter(row["layer_class"].split("+")[0]
                                    for row in rows if row["variant"] == "4k")
    return {
        "artifact": {"path": str(dll.resolve()),
                     "sha256": hashlib.sha256(data).hexdigest()},
        "passes": [
            {k: row[k] for k in (
                "name", "variant", "index", "container_offset", "container_offset_hex",
                "container_size", "dxil_chunk_offset", "dxil_size", "numthreads",
                "wave_size_range", "groupshared_bytes", "resources", "ags", "mulacc",
                "loads", "stores", "converts", "alu", "unary", "binary", "samples",
                "texture_loads", "texture_gathers", "barriers", "atomic_rmw", "loops",
                "a_offsets", "b_offsets", "out_offsets", "template", "layer_class",
                "layer_evidence")}
            for row in rows],
        "templates": [
            {"id": tid, "count": len(members), "passes": [r["index"] for r in members],
             "layer_class": collections.Counter(r["layer_class"] for r in members).most_common(1)[0][0],
             "mulacc": sorted({sum(r["mulacc"].values()) for r in members}),
             "numthreads": sorted({tuple(r["numthreads"] or []) for r in members}),
             "groupshared_bytes": sorted({r["groupshared_bytes"] for r in members})}
            for tid, members in sorted(templates.items(), key=lambda kv: -len(kv[1]))],
        "variant_diff": {
            "pairs": len(pairs),
            "identical_modulo_constants": sum(1 for p in pairs if p["same_code_modulo_constants"]),
            "size_delta_histogram": dict(collections.Counter(
                p["size_delta_bytes"] for p in pairs)),
            "passes_with_zero_literal_deltas": sum(1 for p in pairs if p["literal_delta_count"] == 0),
            "detail": pairs,
        },
        "layer_histogram": dict(histogram),
        "flow": flow[:4000],
        "weights": {
            "static_offset_count": len(static),
            "static_offset_min": min(static) if static else None,
            "static_offset_max": max(static) if static else None,
            "static_offsets": sorted(static)[:2000],
            "dynamic_offset_max": max(dynamic) if dynamic else None,
        },
        "limitations": [
            "Layer classes are heuristics over opcode counts; they name the dominant operation, not a proven mathematical layer.",
            "Loop trip counts and tensor shapes are not recovered: MulAcc counts are static instruction counts.",
            "AGS byte offsets are the constant term of the address expression; dynamic terms come from the constant buffer.",
            "Offsets are byte offsets into the single u0 buffer; equality of offsets across passes is used as a data-flow hint only.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--llvm-dis", default=shutil.which("llvm-dis") or "llvm-dis")
    parser.add_argument("--workdir", type=Path, default=None)
    args = parser.parse_args()
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="mlfi-map-"))
    report = build(args.dll, args.llvm_dis, workdir)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
