#!/usr/bin/env python3
"""Restricted static PRE payload audit, NOT a GPU emulator or general ISA verifier.

Prove only non-reading of original bytes before overwrite/end, under a full,
constant thread execution mask. Branches join with union; predicated writes do
not kill bytes (SEL selects a value rather than suppressing its destination).
Send padding is not data: transpose UGM SIMD1 consumes one A32 address.
Unsupported ISA/IR or changed reviewed identities must not become a safe result.

Accumulator model (minimal, conservative): explicit accN operands are tracked
per overlapping pair, plus the implicit acc0 read of mac/mac/macl (acc0.0
always used). mac/macl never write acc here (no-kill); mach would read+write
but stays rejected. A read of tainted acc is a possible-read.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re

from build_pre_profile import EXPECTED_INPUT, EXPECTED_ZEBIN
from inspect_zebin import inspect, sections

EXPECTED_ASM = 'a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660'
EXPECTED_IR_ASM = '7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e'
GRF_BYTES = 64
GRF_COUNT = 128
TYPES = {'b': 1, 'ub': 1, 'w': 2, 'uw': 2, 'hf': 2, 'bf': 2,
         'd': 4, 'ud': 4, 'f': 4, 'q': 8, 'uq': 8, 'df': 8}
OPS = {'mov', 'and', 'or', 'xor', 'add', 'mul', 'mad', 'mac', 'macl', 'cmp', 'sel',
       'shl', 'shr', 'rnde', 'rndd', 'dpas.8x8', 'math.inv', 'math.log',
       'math.exp', 'math.sqt', 'jmpi', 'nop', 'sync.nop', 'illegal',
       'send.ugm', 'send.smpl', 'send.tgm', 'send.gtwy'}
# Implicit accumulator groups. IGC documents acc0.0 as the always-used implicit
# source for macl (AccWrCtrl NOT set) and for mach (AccWrCtrl set); the IGA
# dependency tables mark MAC/MACH/MACL as implicit acc0 readers. Only acc0
# (group 0, covering the overlapping acc0/acc1 pair) is modelled as implicit;
# explicit accN operands are tracked per overlapping pair (0/1, 2/3, ...).
# mac/macl are modelled as acc readers that never write acc (conservative
# no-kill: assuming a write would unsoundly clear taint). mach would be a
# reader+writer but stays rejected in OPS (fail-closed, not observed here).
IMPLICIT_ACC_READ_OPS = {'mac', 'macl', 'mach'}
IMPLICIT_ACC_WRITE_OPS = {'mach'}


def parse_isa(text):
    instructions, labels = [], {}
    for number, raw in enumerate(text.splitlines(), 1):
        code, _, comment = raw.partition('//')
        code = code.split('{', 1)[0].strip()
        if not code:
            continue
        if re.fullmatch(r'L\d+:', code):
            label = code[:-1]
            if label in labels:
                raise ValueError('Duplicate native label')
            labels[label] = len(instructions)
            continue
        predicate = ''
        match = re.match(r'^\(([^)]+)\)\s*', code)
        if match:
            predicate, code = match.group(1), code[match.end():]
        opcode, _, args = code.partition(' ')
        if opcode not in OPS:
            raise ValueError(f'Unsupported native opcode {opcode}')
        mode = re.search(r'\((\d+)\|M(\d+)\)', args)
        width = int(mode.group(1)) if mode else None
        if mode:
            if mode.group(2) != '0' or width not in (1, 2, 4, 8, 16, 32):
                raise ValueError('Unsupported execution width/group')
            args = args[:mode.start()]+args[mode.end():]
        elif opcode not in {'jmpi', 'nop', 'sync.nop', 'illegal'}:
            raise ValueError('Missing native execution width')
        operands = [t for t in args.split() if not re.fullmatch(r'\([^)]+\)f\d+\.\d+', t)]
        if 'r[' in args or 'a0.' in args:
            raise ValueError('Indirect register addressing not reviewed')
        instructions.append({'line': number, 'op': opcode, 'pred': predicate,
                             'width': width, 'args': operands, 'comment': comment.strip()})
    for ins in instructions:
        if ins['op'] == 'jmpi' and (len(ins['args']) != 1 or ins['args'][0] not in labels):
            raise ValueError('Invalid native branch target')
    return instructions, labels


def register_bytes(token, width, destination=False):
    # Architecture registers, null, immediates and labels cannot alias this GRF.
    if not re.search(r'(?<!\w)r\d', token):
        return set()
    match = re.fullmatch(r'-?(?:\(abs\))?r(\d+)\.(\d+)<([^>]+)>:(\w+)', token)
    if not match or match.group(4) not in TYPES:
        raise ValueError(f'Unsupported typed GRF operand {token}')
    reg, sub, region, typ = match.groups()
    size = TYPES[typ]
    if int(reg) >= GRF_COUNT or int(sub)*size >= GRF_BYTES:
        raise ValueError('Operand outside reviewed GRF namespace')
    start = int(reg)*GRF_BYTES+int(sub)*size
    if destination:
        if not region.isdigit():
            raise ValueError('Unsupported destination region')
        indices = [i*int(region) for i in range(width)]
    elif region in ('0', '0;0'):
        indices = [0]
    elif (m := re.fullmatch(r'(\d+);(\d+),(\d+)', region)):
        vertical, span, horizontal = map(int, m.groups())
        if span == 0:
            raise ValueError('Zero source-region width')
        indices = [(i//span)*vertical+(i % span)*horizontal for i in range(width)]
    else:
        # Unmodelled ternary regions with forward strides: conservatively read
        # everything from this GRF to the end of the reviewed register file.
        # Do not under-approximate their footprint using width alone.
        if not re.fullmatch(r'\d+(?:;\d+)?', region):
            raise ValueError('Unsupported source region')
        return set(range(int(reg)*GRF_BYTES, GRF_COUNT*GRF_BYTES))
    return {start+i*size+b for i in indices for b in range(size)}


def send_register(token, size):
    if token.startswith('null') or size == 0:
        return set()
    match = re.fullmatch(r'r(\d+)(?::\d+)?', token)
    if not match:
        raise ValueError('Unsupported send register')
    start = int(match.group(1))*GRF_BYTES
    return set(range(start, start+size))


def _acc_groups_in_token(token):
    # Overlapping pair grouping: acc0/acc1 share a group, acc2/acc3 share, etc.
    # Conservative for the documented acc overlap (see IGA RegDeps).
    return {(int(n)//2)*2 for n in re.findall(r'acc(\d+)', token)}


def acc_accesses(ins):
    """Return (acc_read_groups, acc_write_groups) for the accumulator file.

    Explicit accN operands plus the implicit acc0 read of mac/macl/mach
    (acc0.0 always used, per IGC BuildIRImpl/RegDeps). mac/macl never write
    acc here (conservative no-kill); mach would read+write but stays
    rejected in OPS. Predicated non-sel writes do not kill, mirroring GRF.
    Send payloads with acc are unreviewed and rejected fail-closed.
    """
    op, args = ins['op'], ins['args']
    if op in {'jmpi', 'nop', 'sync.nop', 'illegal'}:
        return set(), set()
    if op.startswith('send.'):
        if any('acc' in t for t in args):
            raise ValueError('Accumulator in send payload not reviewed')
        return set(), set()
    if not args:
        raise ValueError('Missing data operands')
    read, write = set(), set()
    if 'acc' in args[0]:
        write.update(_acc_groups_in_token(args[0]))
    for token in args[1:]:
        if 'acc' in token:
            read.update(_acc_groups_in_token(token))
    if op in IMPLICIT_ACC_READ_OPS:
        read.add(0)
    if op in IMPLICIT_ACC_WRITE_OPS:
        write.add(0)
    if 'f' in ins['pred'] and op != 'sel':
        write = set()
    return read, write


def accesses(ins):
    op, args, width = ins['op'], ins['args'], ins['width']
    conditional = 'f' in ins['pred']
    if op in {'jmpi', 'nop', 'sync.nop', 'illegal'}:
        return set(), set()
    if op.startswith('send.'):
        if len(args) != 5:
            raise ValueError('Unsupported send operands')
        sizes = re.search(r'wr:(\d+)\+(\d+), rd:(\d+);', ins['comment'])
        if not sizes:
            raise ValueError('Missing decoded message lengths')
        n0, n1, nd = (int(n)*GRF_BYTES for n in sizes.groups())
        transpose = re.search(r'\b(load|store)\.ugm\.d32x(\d+)t\.a32\.', ins['comment'])
        if transpose:
            if width != 1:
                raise ValueError('Transpose is only modelled for SIMD1')
            operation, components = transpose.groups()
            n0 = 4  # One scalar A32 address, NOT the entire allocated GRF.
            if operation == 'load':
                if n1:
                    raise ValueError('Unexpected load data input')
                nd = int(components)*4
            else:
                n1 = int(components)*4
                if nd:
                    raise ValueError('Unexpected store response')
        reads = send_register(args[1], n0) | send_register(args[2], n1)
        # Descriptors are literal immediates in the reviewed binary.
        if any(not re.fullmatch(r'0x[0-9A-Fa-f]+', t) for t in args[3:]):
            raise ValueError('Register-based message descriptor not reviewed')
        writes = send_register(args[0], nd)
        return reads, set() if conditional else writes
    if not args:
        raise ValueError('Missing data operands')
    reads = set().union(*(register_bytes(t, width) for t in args[1:]))
    writes = register_bytes(args[0], width, destination=True)
    return reads, set() if conditional and op != 'sel' else writes


def audit_native(text, seed_line, seed_register=2, seed_size=32):
    instructions, labels = parse_isa(text)
    seeds = [i for i, ins in enumerate(instructions) if ins['line'] == seed_line]
    if len(seeds) != 1 or seeds[0]+1 >= len(instructions):
        raise ValueError('Missing seed instruction or continuation')
    start = seeds[0]+1
    original = set(range(seed_register*GRF_BYTES, seed_register*GRF_BYTES+seed_size))
    # Per-program-point state is (grf_live, acc_live). grf_live holds original
    # byte identities still present in r2; acc_live maps accumulator pair-group
    # -> set of original byte identities currently possibly held there.
    # Accumulators start clean: the cross-thread payload is only in r2.
    states = {start: (set(original), {})}
    queue, reads, kills, visited = deque([start]), {}, {}, set()
    while queue:
        index = queue.popleft()
        live, acc_live = states[index]
        if not live and all(not v for v in acc_live.values()):
            continue
        ins = instructions[index]
        visited.add(index)
        used, written = accesses(ins)
        acc_read, acc_write = acc_accesses(ins)
        if live & used:
            prev = set(reads.get(ins['line'], []))
            prev.update(b-seed_register*GRF_BYTES for b in live & used)
            reads[ins['line']] = sorted(prev)
        acc_taint_read = set()
        for group in acc_read:
            acc_taint_read |= acc_live.get(group, set())
        if acc_taint_read:
            prev = set(reads.get(ins['line'], []))
            prev.update(b-seed_register*GRF_BYTES for b in acc_taint_read)
            reads[ins['line']] = sorted(prev)
        removed = live & written
        if removed:
            prev = set(kills.get(ins['line'], []))
            prev.update(b-seed_register*GRF_BYTES for b in removed)
            kills[ins['line']] = sorted(prev)
        outgoing = live-written
        # Accumulator transfer: new value derives from live GRF sources plus
        # any acc taint read. Unconditional writes replace; predicated
        # non-sel writes may or may not happen, so they union (no kill).
        new_from_grf = live & used
        outgoing_acc = dict(acc_live)
        for group in acc_write:
            outgoing_acc[group] = set(new_from_grf) | set(acc_taint_read)
        conditional = 'f' in ins['pred'] and ins['op'] != 'sel'
        if conditional:
            dst = ins['args'][0] if ins['args'] else ''
            if 'acc' in dst:
                for group in _acc_groups_in_token(dst):
                    outgoing_acc[group] = (outgoing_acc.get(group, set())
                                           | set(new_from_grf) | set(acc_taint_read))
            if ins['op'] in IMPLICIT_ACC_WRITE_OPS:
                outgoing_acc[0] = (outgoing_acc.get(0, set())
                                   | set(new_from_grf) | set(acc_taint_read))
        if ins['op'] == 'illegal':
            raise ValueError('Reached illegal/padding with live original bytes')
        if 'end of thread' in ins['comment']:
            successors = []
        elif ins['op'] == 'jmpi':
            successors = [labels[ins['args'][0]]]
            if 'f' in ins['pred']:
                successors.append(index+1)
        else:
            successors = [index+1]
        for successor in successors:
            if successor >= len(instructions):
                raise ValueError('Live data reached an invalid native continuation')
            prev_live, prev_acc = states.get(successor, (set(), {}))
            merged_live = prev_live | outgoing
            merged_acc = dict(prev_acc)
            for group, taint in outgoing_acc.items():
                merged_acc[group] = merged_acc.get(group, set()) | taint
            # Prune empty acc groups to keep state comparison stable.
            merged_acc = {g: v for g, v in merged_acc.items() if v}
            prev_acc_pruned = {g: v for g, v in prev_acc.items() if v}
            if merged_live != prev_live or merged_acc != prev_acc_pruned:
                states[successor] = (merged_live, merged_acc)
                queue.append(successor)
    return {'status': 'possible-read' if reads else 'unread-before-overwrite-or-end',
            'assumptions': ['full constant thread execution mask', '64-byte GRFs',
                            'decoded IGA send descriptions agree with native encoding'],
            'seed_line': seed_line, 'seed_register': seed_register, 'seed_size': seed_size,
            'visited_instructions_with_live_bytes': len(visited),
            'possible_reads': [{'line': n, 'offsets': b} for n, b in sorted(reads.items())],
            'overwrites': [{'line': n, 'offsets': b} for n, b in sorted(kills.items())]}


def audit_ir(text):
    ids = r'%[\w.]+'
    names = dict(re.findall(r'OpDecorate\s+('+ids+r') LinkageAttributes "([^"]+)" Import', text))
    functions, definitions, current = {}, {}, None
    entry = re.findall(r'OpEntryPoint Kernel ('+ids+r') "fsr4_pre_xmx"', text)
    if len(entry) != 1:
        raise ValueError('Missing exact PRE entry')
    for line in text.splitlines():
        m = re.match(r'\s*('+ids+r') = (Op\w+)\s*(.*)', line)
        if m:
            result, op, operands = m.groups()
            definitions[result] = (op, operands)
            if op == 'OpFunction':
                current = {'params': [], 'body': []}
                functions[result] = current
            elif op == 'OpFunctionParameter':
                if current is None:
                    raise ValueError('Parameter outside function')
                current['params'].append((result, operands.strip()))
            elif current is not None:
                current['body'].append((result, op, operands))
        elif 'OpFunctionEnd' in line:
            current = None
        elif current is not None:
            m = re.match(r'\s*(Op\w+)\s*(.*)', line)
            if m:
                current['body'].append((None, *m.groups()))
    wrapper = functions[entry[0]]
    calls = [x for x in wrapper['body'] if x[1] == 'OpFunctionCall']
    if len(wrapper['params']) != 12 or len(calls) != 1:
        raise ValueError('Unexpected PRE entry wrapper')
    operands = calls[0][2].split()
    callee, args = operands[1], operands[2:]
    if args != [p for p, _ in wrapper['params']]:
        raise ValueError('Wrapper reorders arguments')
    body = functions[callee]
    if len(body['params']) != 12:
        raise ValueError('Unexpected PRE body parameters')
    results = []
    for i in (0, 9, 10):
        param, typ = body['params'][i]
        if definitions.get(typ) != ('OpTypeBufferSurfaceINTEL', 'ReadWrite'):
            raise ValueError('Expected opaque CM buffer surface')
        uses = [x for x in body['body'] if param in re.findall(ids, x[2])]
        if len(uses) != 1 or uses[0][1] != 'OpFunctionCall':
            raise ValueError('Buffer surface has unreviewed IR uses')
        called = uses[0][2].split()
        if len(called) != 3 or called[2] != param or names.get(called[1]) != 'llvm.genx.address.convert.i32.p1intel.buffer_rw_t':
            raise ValueError('Expected sole SurfaceIndex conversion')
        results.append({'arg_index': i, 'parameter': param, 'type': 'opaque CM buffer surface',
                        'sole_use': 'llvm.genx.address.convert.i32.p1intel.buffer_rw_t'})
    return results


def build_report(source, zebin, assembly, ir):
    if hashlib.sha256(source).hexdigest() != EXPECTED_INPUT:
        raise ValueError('Unreviewed CM input')
    if hashlib.sha256(zebin).hexdigest() != EXPECTED_ZEBIN:
        raise ValueError('Unreviewed zebin')
    if hashlib.sha256(assembly).hexdigest() != EXPECTED_ASM:
        raise ValueError('Unreviewed native disassembly')
    if hashlib.sha256(ir).hexdigest() != EXPECTED_IR_ASM:
        raise ValueError('Unreviewed embedded IR disassembly')
    named = sections(zebin)
    if source[:len(named['.spv'])] != named['.spv']:
        raise ValueError('Embedded SPIR-V does not match reviewed input')
    report = inspect(zebin, 'fsr4_pre_xmx')
    native = assembly.decode('utf-8')
    instructions, _ = parse_isa(native)
    seeds = [ins for ins in instructions if ins['op'] == 'send.ugm' and ins['args'][0] == 'r2'
             and 'load.ugm.d32x8t.a32.ca.cc.bti[255]' in ins['comment']]
    if len(seeds) != 1:
        raise ValueError('Missing reviewed cross-thread prologue load')
    payload = [p for p in report['payload_arguments'] if p.get('size', 0)]
    if [(p['offset'], p['size']) for p in payload] != [(8, 8), (16, 8), (24, 8), (0, 8)]:
        raise ValueError('Changed nonzero pointer payload')
    return {'schema_version': 1, 'status': 'static-analysis-only',
            'input_sha256': hashlib.sha256(source).hexdigest(),
            'zebin_sha256': report['zebin_sha256'], 'code_sha256': report['code_sha256'],
            'assembly_sha256': hashlib.sha256(assembly).hexdigest(),
            'embedded_spirv_sha256': hashlib.sha256(named['.spv']).hexdigest(),
            'ir_assembly_sha256': hashlib.sha256(ir).hexdigest(),
            'ir_surface_parameters': audit_ir(ir.decode('utf-8')),
            'nonzero_payload_fields': payload,
            'native_byte_liveness': audit_native(native, seeds[0]['line']),
            'runtime_approved': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cmspv', type=Path)
    p.add_argument('zebin', type=Path)
    p.add_argument('native_asm', type=Path)
    p.add_argument('spirv_asm', type=Path, help='spirv-dis output of embedded .spv')
    a = p.parse_args()
    report = build_report(a.cmspv.read_bytes(), a.zebin.read_bytes(),
                          a.native_asm.read_bytes(), a.spirv_asm.read_bytes())
    print(json.dumps(report, indent=2))
    if report['native_byte_liveness']['possible_reads']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
