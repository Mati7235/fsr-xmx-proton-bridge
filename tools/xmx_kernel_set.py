#!/usr/bin/env python3
"""GPU-level XMX kernel-set comparison (offline, read-only).

Parses vkd3d `ANV CM: ... injected <path>.cmk (<N> bytes code, <G> GRF, ...)`
lines and fingerprints the native code of each referenced `.cmk` file:

    <code_sha256>:<code_size>:<grf>

CMK2 layout: 472-byte header, `code_size` u32 LE at offset 4, native code
after the header. Files are resolved by basename inside `--kernels-dir`;
a referenced file that is absent is reported as `MISSING:<hash>` (the
filename stem before the first `_`) instead of failing.

Subcommands:
  fingerprint <vkd3d.log> <kernels_dir> [-o out.txt]
  diff <fp1> <fp2> [--logs --kernels-dir DIR]

`diff` prints COMUNES / SOLO_A / SOLO_B sections with counts. Exit 0 when
the sets are identical, 1 when they differ, 2 on usage/IO errors.
Never launches games, Proton, or touches prefixes/drivers.
"""
import argparse
import hashlib
import re
import struct
import sys
from pathlib import Path

CMK2_MAGIC = b"CMK2"
CMK2_HEADER_SIZE = 472
_CHUNK = 1 << 20

INJECTED_RE = re.compile(
    r"injected\s+(\S+\.cmk)\s+\((\d+)\s+bytes code,\s*(\d+)\s+GRF"
)


def _stem_hash(basename):
    return basename.split("_")[0]


def fingerprint_entries(log_path, kernels_dir):
    """Single streaming pass over the log; yields (basename, grf) refs."""
    refs = {}  # basename -> grf (first seen wins; log GRF is authoritative)
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = INJECTED_RE.search(line)
            if not m:
                continue
            basename = m.group(1).split("/")[-1]
            if basename not in refs:
                refs[basename] = m.group(3)
    out = []
    kernels_dir = Path(kernels_dir)
    for basename in sorted(refs):
        grf = refs[basename]
        path = kernels_dir / basename
        try:
            with open(path, "rb") as fh:
                header = fh.read(CMK2_HEADER_SIZE)
                if len(header) < CMK2_HEADER_SIZE or header[:4] != CMK2_MAGIC:
                    out.append("BAD:%s" % _stem_hash(basename))
                    continue
                (code_size,) = struct.unpack_from("<I", header, 4)
                if not 0 < code_size <= 16 * 1024 * 1024:
                    out.append("BAD:%s" % _stem_hash(basename))
                    continue
                h = hashlib.sha256()
                remaining = code_size
                ok = True
                while remaining > 0:
                    chunk = fh.read(min(_CHUNK, remaining))
                    if not chunk:
                        ok = False
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
                if not ok:
                    out.append("BAD:%s" % _stem_hash(basename))
                    continue
                out.append("%s:%d:%s" % (h.hexdigest(), code_size, grf))
        except (OSError, ValueError):
            out.append("MISSING:%s" % _stem_hash(basename))
    return sorted(out)


def _read_fp(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return sorted(line.strip() for line in f if line.strip())


def cmd_fingerprint(args):
    log = Path(args.log)
    kdir = Path(args.kernels_dir)
    if not log.is_file():
        print("error: log not found: %s" % log, file=sys.stderr)
        return 2
    if not kdir.is_dir():
        print("error: kernels dir not found: %s" % kdir, file=sys.stderr)
        return 2
    try:
        entries = fingerprint_entries(str(log), str(kdir))
    except OSError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    text = "".join(e + "\n" for e in entries)
    if args.output:
        try:
            Path(args.output).write_text(text, encoding="utf-8")
        except OSError as e:
            print("error: %s" % e, file=sys.stderr)
            return 2
    else:
        sys.stdout.write(text)
    return 0


def cmd_diff(args):
    try:
        if args.logs:
            if not args.kernels_dir:
                print("error: diff --logs requires --kernels-dir DIR",
                      file=sys.stderr)
                return 2
            set_a = fingerprint_entries(args.a, args.kernels_dir)
            set_b = fingerprint_entries(args.b, args.kernels_dir)
        else:
            set_a = _read_fp(args.a)
            set_b = _read_fp(args.b)
    except OSError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    a, b = set(set_a), set(set_b)
    comunes = sorted(a & b)
    solo_a = sorted(a - b)
    solo_b = sorted(b - a)
    sys.stdout.write("COMUNES %d\n" % len(comunes))
    for e in comunes:
        sys.stdout.write("  %s\n" % e)
    sys.stdout.write("SOLO_A %d\n" % len(solo_a))
    for e in solo_a:
        sys.stdout.write("  %s\n" % e)
    sys.stdout.write("SOLO_B %d\n" % len(solo_b))
    for e in solo_b:
        sys.stdout.write("  %s\n" % e)
    return 0 if not solo_a and not solo_b else 1


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("fingerprint", help="fingerprint kernels of one run")
    pf.add_argument("log", help="vkd3d log path (read-only)")
    pf.add_argument("kernels_dir", help="kernel cache dir (read-only)")
    pf.add_argument("-o", "--output", default=None,
                    help="write fingerprint file instead of stdout")
    pf.set_defaults(func=cmd_fingerprint)
    pd = sub.add_parser("diff", help="compare two kernel sets")
    pd.add_argument("a", help="fingerprint file A (or log A with --logs)")
    pd.add_argument("b", help="fingerprint file B (or log B with --logs)")
    pd.add_argument("--logs", action="store_true",
                    help="interpret A/B as vkd3d logs, not fingerprints")
    pd.add_argument("--kernels-dir", default=None)
    pd.set_defaults(func=cmd_diff)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
