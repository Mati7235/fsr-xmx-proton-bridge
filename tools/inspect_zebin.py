#!/usr/bin/env python3
"""Inspect ELF64 zebin and the restricted .ze_info shape emitted by this toolchain.

No GPU execution, dynamic loading, or third-party Python modules. Not a general
YAML parser: unsupported/missing scalar/list fields must be treated explicitly.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def sections(data):
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64')
    offset, = struct.unpack_from('<Q', data, 0x28)
    stride, count, names_index = struct.unpack_from('<HHH', data, 0x3a)
    if stride < 64 or not 0 < count <= 4096 or names_index >= count:
        raise ValueError('Unsupported ELF section table')
    if offset+stride*count > len(data):
        raise ValueError('Truncated ELF section table')
    entries = []
    for i in range(count):
        name, typ, flags, addr, pos, size = struct.unpack_from('<IIQQQQ', data, offset+i*stride)
        if typ == 8:  # SHT_NOBITS has no bytes in the file.
            entries.append((name, b''))
        else:
            if pos+size > len(data):
                raise ValueError('Section outside ELF file')
            entries.append((name, data[pos:pos+size]))
    names = entries[names_index][1]
    result = {}
    for name, blob in entries:
        if name >= len(names):
            raise ValueError('Invalid section name offset')
        end = names.find(b'\0', name)
        if end < 0:
            raise ValueError('Unterminated section name')
        label = names[name:end].decode('utf-8')
        if label in result:
            raise ValueError('Duplicate ELF section name')
        result[label] = blob
    return result


def scalar(text):
    if text in ('true', 'false'):
        return text == 'true'
    if re.fullmatch(r'[0-9]+', text):
        return int(text)
    return text


def metadata(info, kernel):
    blocks = re.split(r'^  - name:\s*', info, flags=re.M)[1:]
    selected = [b for b in blocks if b.splitlines()[0].strip() == kernel]
    if len(selected) != 1:
        raise ValueError('Missing or ambiguous exact kernel name')
    block = selected[0]
    result = {'kernel': kernel}
    for key in ('execution_env', 'payload_arguments', 'per_thread_payload_arguments', 'binding_table_indices'):
        match = re.search(r'^    '+key+r':\s*\n(.*?)(?=^    [A-Za-z_]+:|\Z)', block, re.M | re.S)
        part = match.group(1) if match else ''
        if key == 'execution_env':
            result[key] = {k: scalar(v.strip()) for k, v in re.findall(r'^      (\w+):\s*([^\n]+)', part, re.M)}
        else:
            records = []
            for record in re.split(r'^      - ', part, flags=re.M)[1:]:
                pairs = re.findall(r'^\s*(\w+):\s*([^\n]+)', record, re.M)
                records.append({k: scalar(v.strip()) for k, v in pairs})
            result[key] = records
    return result


def inspect(data, kernel):
    named = sections(data)
    code = named.get('.text.'+kernel)
    if code is None or '.ze_info' not in named:
        raise ValueError('Missing selected code or metadata section')
    result = metadata(named['.ze_info'].decode('utf-8'), kernel)
    result.update({'zebin_sha256': hashlib.sha256(data).hexdigest(),
                   'code_size': len(code), 'code_sha256': hashlib.sha256(code).hexdigest(),
                   'sections': {name: {'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
                                for name, blob in named.items() if name}})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('zebin', type=Path)
    p.add_argument('--kernel', required=True)
    p.add_argument('--extract', type=Path, help='New directory for selected metadata sections')
    a = p.parse_args()
    data = a.zebin.read_bytes()
    report = inspect(data, a.kernel)
    if a.extract:
        a.extract.mkdir(parents=True, exist_ok=False)
        named = sections(data)
        for section, filename in [('.ze_info', 'ze_info.yaml'), ('.misc.buildOptions', 'build-options.bin')]:
            if section in named:
                (a.extract/filename).write_bytes(named[section])
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
