#!/usr/bin/env python3
"""CPU-only comparison of raw GPU readback dumps (RenderDoc captures, etc.).

Subcommands:
  inspect  sanity stats of one dump (NaN/Inf counts, min/max/mean).
  diff     bitwise and tolerance comparison of two dumps.
  metrics  PSNR and SSIM of a candidate dump against a reference dump.

Only the Python standard library is required. If numpy is importable it is
used as a fast path; setting FSR_READBACK_NO_NUMPY=1 forces the pure-python
fallback (same results up to floating point summation order).
"""

import argparse
import math
import os
import sys
from array import array
from pathlib import Path

USE_NUMPY = True
if os.environ.get("FSR_READBACK_NO_NUMPY"):
    USE_NUMPY = False
else:
    try:
        import numpy as _np  # noqa: F401
    except ImportError:
        USE_NUMPY = False

# prefix -> channel count
_PREFIX_CHANNELS = {"r": 1, "rg": 2, "rgb": 3, "rgba": 4}
# suffix -> (kind, bytes per component)
_SUFFIX_COMP = {"8": ("u8", 1), "16f": ("f16", 2), "32f": ("f32", 4)}

DEFAULT_MAX_DIFFS = 10
SSIM_WINDOW = 8  # non-overlapping box window, edge partial windows included
SSIM_K1 = 0.01
SSIM_K2 = 0.03


def parse_format(text):
    """Return (channels, kind, bytes_per_component) or raise ValueError."""
    name = text.strip().lower()
    for prefix in ("rgba", "rgb", "rg", "r"):
        if name.startswith(prefix):
            suffix = name[len(prefix):]
            if suffix in _SUFFIX_COMP:
                kind, bpc = _SUFFIX_COMP[suffix]
                return _PREFIX_CHANNELS[prefix], kind, bpc
    raise ValueError(
        "unsupported format %r (expected like rgba32f, rgba16f, rgb8, r32f)" % (text,))


def row_bytes(width, channels, bpc):
    return width * channels * bpc


def expected_size(width, height, channels, bpc, stride):
    pitch = row_bytes(width, channels, bpc)
    if stride is None:
        return pitch * height
    if stride < pitch:
        raise ValueError(
            "stride %d smaller than row size %d" % (stride, pitch))
    return stride * height


def check_positive_int(value, name):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a positive integer, got %r" % (name, value))
    if number <= 0:
        raise ValueError("%s must be a positive integer, got %r" % (name, value))
    return number


def default_peak(kind):
    return 255.0 if kind == "u8" else 1.0


_HALF_TABLE = None


def _half_table():
    global _HALF_TABLE
    if _HALF_TABLE is None:
        table = [0.0] * 65536
        for bits in range(65536):
            sign = -1.0 if bits & 0x8000 else 1.0
            exp = (bits >> 10) & 0x1F
            mant = bits & 0x3FF
            if exp == 0:
                table[bits] = sign * (mant / 1024.0) * (2.0 ** -14)
            elif exp == 31:
                table[bits] = (math.nan if mant else math.inf) * sign
                if mant:
                    table[bits] = math.nan
            else:
                table[bits] = sign * (1.0 + mant / 1024.0) * (2.0 ** (exp - 15))
        _HALF_TABLE = table
    return _HALF_TABLE


def decode_values(data, channels, kind, width, height, stride):
    """Decode a dump to a flat list of floats (row-major, padding removed).

    Uses numpy when available; otherwise pure stdlib. Raises ValueError on
    size mismatch or truncated rows.
    """
    bpc = {"u8": 1, "f16": 2, "f32": 4}[kind]
    pitch = row_bytes(width, channels, bpc)
    total = expected_size(width, height, channels, bpc, stride)
    if len(data) != total:
        raise ValueError(
            "size mismatch: got %d bytes, expected %d "
            "(format %d channels x %s, %dx%d, stride %s)" % (
                len(data), total, channels, kind, width, height,
                stride if stride is not None else pitch))
    rows = []
    step = stride if stride is not None else pitch
    for y in range(height):
        rows.append(data[y * step:y * step + pitch])
    packed = b"".join(rows)
    count = width * height * channels
    if USE_NUMPY:
        import numpy as np
        if kind == "u8":
            return np.frombuffer(packed, dtype=np.uint8).astype(np.float64)
        if kind == "f32":
            return np.frombuffer(packed, dtype="<f4").astype(np.float64)
        words = np.frombuffer(packed, dtype="<u2").astype(np.int64)
        sign = np.where(words & 0x8000, -1.0, 1.0)
        exp = (words >> 10) & 0x1F
        mant = words & 0x3FF
        out = np.empty(count, dtype=np.float64)
        norm = (exp != 0) & (exp != 31)
        out[norm] = sign[norm] * (1.0 + mant[norm] / 1024.0) * 2.0 ** (exp[norm] - 15)
        sub = exp == 0
        out[sub] = sign[sub] * (mant[sub] / 1024.0) * 2.0 ** -14
        inf = exp == 31
        out[inf & (mant == 0)] = np.inf * sign[inf & (mant == 0)]
        out[inf & (mant != 0)] = np.nan
        return out
    if kind == "u8":
        return [float(b) for b in packed]
    if kind == "f32":
        words = array("f")
        words.frombytes(packed)
        if sys.byteorder != "little":
            words.byteswap()
        return [float(v) for v in words]
    words = array("H")
    words.frombytes(packed)
    if sys.byteorder != "little":
        words.byteswap()
    table = _half_table()
    return [table[w] for w in words]


def _to_list(values):
    if USE_NUMPY:
        return values.tolist()
    return values


def _finite_stats(values):
    """Return dict with nan/inf counts, min/max/mean over finite values."""
    total = len(values)
    if USE_NUMPY:
        import numpy as np
        arr = values
        nan = int(np.isnan(arr).sum())
        pinf = int(np.isposinf(arr).sum())
        ninf = int(np.isneginf(arr).sum())
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return {"total": total, "nan": nan, "posinf": pinf,
                    "neginf": ninf, "finite": 0, "min": math.nan,
                    "max": math.nan, "mean": math.nan}
        return {"total": total, "nan": nan, "posinf": pinf, "neginf": ninf,
                "finite": int(finite.size), "min": float(finite.min()),
                "max": float(finite.max()), "mean": float(finite.mean())}
    nan = pinf = ninf = 0
    minimum = math.inf
    maximum = -math.inf
    acc = 0.0
    finite = 0
    for v in values:
        if math.isnan(v):
            nan += 1
        elif v == math.inf:
            pinf += 1
        elif v == -math.inf:
            ninf += 1
        else:
            finite += 1
            acc += v
            if v < minimum:
                minimum = v
            if v > maximum:
                maximum = v
    if finite == 0:
        return {"total": total, "nan": nan, "posinf": pinf, "neginf": ninf,
                "finite": 0, "min": math.nan, "max": math.nan, "mean": math.nan}
    return {"total": total, "nan": nan, "posinf": pinf, "neginf": ninf,
            "finite": finite, "min": minimum, "max": maximum,
            "mean": acc / finite}


def _channel_means(values, channels):
    """Per-channel mean over finite values (nan if a channel has none)."""
    if USE_NUMPY:
        import numpy as np
        arr = values.reshape(-1, channels)
        means = []
        for c in range(channels):
            col = arr[:, c]
            fin = col[np.isfinite(col)]
            means.append(float(fin.mean()) if fin.size else math.nan)
        return means
    acc = [0.0] * channels
    cnt = [0] * channels
    for i, v in enumerate(values):
        if math.isfinite(v):
            c = i % channels
            acc[c] += v
            cnt[c] += 1
    return [(acc[c] / cnt[c]) if cnt[c] else math.nan for c in range(channels)]


def cmd_inspect(args):
    try:
        channels, kind, bpc = parse_format(args.format)
        width = check_positive_int(args.width, "width")
        height = check_positive_int(args.height, "height")
        stride = None
        if args.stride is not None:
            stride = check_positive_int(args.stride, "stride")
        data = args.dump.read_bytes()
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    try:
        values = decode_values(data, channels, kind, width, height, stride)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    stats = _finite_stats(values)
    means = _channel_means(values, channels)
    names = ("R", "G", "B", "A") if channels > 1 else ("C0",)
    pitch = row_bytes(width, channels, bpc)
    print("format: %s (%d channels x %s)" % (args.format, channels, kind))
    print("dimensions: %d x %d" % (width, height))
    print("row_bytes: %d" % pitch)
    print("stride: %s" % (stride if stride is not None else pitch))
    print("expected_size: %d" % expected_size(width, height, channels, bpc, stride))
    print("actual_size: %d" % len(data))
    print("total_values: %d" % stats["total"])
    print("finite: %d" % stats["finite"])
    print("nan: %d" % stats["nan"])
    print("posinf: %d" % stats["posinf"])
    print("neginf: %d" % stats["neginf"])
    print("min: %r" % stats["min"])
    print("max: %r" % stats["max"])
    print("mean: %r" % stats["mean"])
    for c in range(channels):
        print("mean_%s: %r" % (names[c] if c < len(names) else ("C%d" % c), means[c]))
    return 0


def _raw_words(data, kind):
    """Raw integer bit patterns per value for bitwise comparison."""
    if kind == "u8":
        return array("B", data)
    n = {"f16": 2, "f32": 4}[kind]
    if len(data) % n:
        raise ValueError("byte length %d not a multiple of %d" % (len(data), n))
    fmt = "H" if n == 2 else "I"
    words = array(fmt)
    words.frombytes(data)
    if sys.byteorder != "little":
        words.byteswap()
    return words


def cmd_diff(args):
    try:
        tolerance = float(args.tolerance)
    except (TypeError, ValueError):
        print("error: tolerance must be a number, got %r" % args.tolerance,
              file=sys.stderr)
        return 2
    if not math.isfinite(tolerance) or tolerance < 0:
        print("error: tolerance must be a finite value >= 0", file=sys.stderr)
        return 2
    max_diffs = args.max_diffs
    try:
        max_diffs = int(max_diffs)
    except (TypeError, ValueError):
        print("error: max-diffs must be an integer", file=sys.stderr)
        return 2
    if max_diffs < 0:
        print("error: max-diffs must be >= 0", file=sys.stderr)
        return 2
    try:
        raw_a = args.a.read_bytes()
        raw_b = args.b.read_bytes()
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if len(raw_a) != len(raw_b):
        print("error: size mismatch: a=%d bytes, b=%d bytes"
              % (len(raw_a), len(raw_b)), file=sys.stderr)
        return 2
    channels = kind = width = height = None
    values_a = values_b = None
    if args.format is not None or args.width is not None or args.height is not None:
        if args.format is None or args.width is None or args.height is None:
            print("error: --format, --width and --height must be given together",
                  file=sys.stderr)
            return 2
        try:
            channels, kind, bpc = parse_format(args.format)
            width = check_positive_int(args.width, "width")
            height = check_positive_int(args.height, "height")
            values_a = decode_values(raw_a, channels, kind, width, height, None)
            values_b = decode_values(raw_b, channels, kind, width, height, None)
        except ValueError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
    else:
        # Default: raw bytes must decode as little-endian float32 words.
        kind = "f32"
        channels = 1
        if len(raw_a) % 4:
            print("error: byte length %d not a multiple of 4; "
                  "pass --format/--width/--height for other layouts" % len(raw_a),
                  file=sys.stderr)
            return 2
        try:
            words_a = _raw_words(raw_a, "f32")
            words_b = _raw_words(raw_b, "f32")
        except ValueError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
        if USE_NUMPY:
            import numpy as np
            values_a = np.frombuffer(raw_a, dtype="<f4").astype(np.float64)
            values_b = np.frombuffer(raw_b, dtype="<f4").astype(np.float64)
        else:
            fa = array("f")
            fa.frombytes(raw_a)
            fb = array("f")
            fb.frombytes(raw_b)
            if sys.byteorder != "little":
                fa.byteswap()
                fb.byteswap()
            values_a = [float(v) for v in fa]
            values_b = [float(v) for v in fb]
    if raw_a == raw_b:
        print("identical: True (bitwise equal, %d bytes)" % len(raw_a))
        print("different_values: 0")
        print("max_abs_error: 0.0")
        print("max_rel_error: 0.0")
        return 0
    # Bitwise-different: locate per-value differences.
    if USE_NUMPY:
        import numpy as np
        la = _to_list(values_a)
        lb = _to_list(values_b)
    else:
        la = values_a
        lb = values_b
    if kind in ("f32", "f16"):
        try:
            wa = _raw_words(raw_a if args.format is None else _pack_rows(
                raw_a, channels, kind, width, height), kind)
            wb = _raw_words(raw_b if args.format is None else _pack_rows(
                raw_b, channels, kind, width, height), kind)
            bit_diff = [int(x != y) for x, y in zip(wa, wb)]
        except ValueError:
            bit_diff = None
    else:
        bit_diff = [1 if x != y else 0 for x, y in zip(raw_a, raw_b)]
        la = [float(x) for x in raw_a]
        lb = [float(x) for x in raw_b]
    n = len(la)
    if bit_diff is None or len(bit_diff) != n:
        bit_diff = [0] * n
        for i in range(n):
            a, b = la[i], lb[i]
            if isinstance(a, float) and isinstance(b, float):
                if math.isnan(a) and math.isnan(b):
                    continue
            if a != b:
                bit_diff[i] = 1
    different = sum(bit_diff)
    max_abs = 0.0
    max_rel = 0.0
    shown = 0
    pending = []
    for i in range(n):
        if not bit_diff[i]:
            continue
        a, b = float(la[i]), float(lb[i])
        if math.isnan(a) or math.isnan(b):
            abs_err = math.inf
            rel_err = math.inf
        else:
            abs_err = abs(a - b)
            denom = max(abs(a), abs(b))
            rel_err = (abs_err / denom) if denom else (0.0 if abs_err == 0 else math.inf)
        if abs_err > max_abs or (math.isinf(abs_err) and not math.isinf(max_abs)):
            max_abs = abs_err
        if rel_err > max_rel or (math.isinf(rel_err) and not math.isinf(max_rel)):
            max_rel = rel_err
        if shown < max_diffs:
            if width is not None and channels is not None:
                pix, ch = divmod(i, channels)
                y, x = divmod(pix, width)
                coord = "x=%d y=%d c=%d" % (x, y, ch)
            else:
                coord = "index=%d" % i
            pending.append("diff %d: %s a=%r b=%r abs=%r rel=%r"
                           % (i, coord, a, b, abs_err, rel_err))
            shown += 1
    print("identical: False")
    print("different_values: %d of %d" % (different, n))
    print("max_abs_error: %r" % max_abs)
    print("max_rel_error: %r" % max_rel)
    for line in pending:
        print(line)
    if max_abs <= tolerance:
        print("within_tolerance: True (tolerance=%r; bits differ "
              "but values agree)" % tolerance)
        return 0
    print("within_tolerance: False (tolerance=%r)" % tolerance)
    return 1


def _pack_rows(data, channels, kind, width, height):
    bpc = {"u8": 1, "f16": 2, "f32": 4}[kind]
    pitch = row_bytes(width, channels, bpc)
    if len(data) != pitch * height:
        raise ValueError("size mismatch for diff layout")
    return data


def _mse_psnr(la, lb, peak):
    n = len(la)
    acc = 0.0
    for i in range(n):
        d = la[i] - lb[i]
        acc += d * d
    mse = acc / n if n else math.nan
    if mse == 0:
        return mse, math.inf
    if peak <= 0 or not math.isfinite(peak):
        return mse, math.nan
    return mse, 20.0 * math.log10(peak) - 10.0 * math.log10(mse)


def _luminance(values, width, height, channels):
    """Rec.709 luma for RGB/RGBA, else first channel. Returns flat list."""
    pixels = width * height
    if channels < 3:
        if USE_NUMPY:
            return values.reshape(-1, channels)[:, 0].copy()
        return [values[p * channels] for p in range(pixels)]
    if USE_NUMPY:
        import numpy as np
        m = values.reshape(-1, channels)
        return 0.2126 * m[:, 0] + 0.7152 * m[:, 1] + 0.0722 * m[:, 2]
    out = [0.0] * pixels
    for p in range(pixels):
        base = p * channels
        out[p] = (0.2126 * values[base] + 0.7152 * values[base + 1]
                  + 0.0722 * values[base + 2])
    return out


def _ssim_tile_pass(xs, ys, width, height, np_mod, peak):
    """Mean SSIM over non-overlapping SSIM_WINDOW x SSIM_WINDOW boxes."""
    c1 = (SSIM_K1 * peak) ** 2
    c2 = (SSIM_K2 * peak) ** 2
    total = 0.0
    count = 0
    W = SSIM_WINDOW
    for y0 in range(0, height, W):
        y1 = min(y0 + W, height)
        for x0 in range(0, width, W):
            x1 = min(x0 + W, width)
            idx = []
            for y in range(y0, y1):
                base = y * width
                for x in range(x0, x1):
                    idx.append(base + x)
            m = len(idx)
            if np_mod is not None:
                import numpy as _np
                xv = _np.take(xs, idx)
                yv = _np.take(ys, idx)
                mx = float(xv.mean())
                my = float(yv.mean())
                vx = float((xv * xv).mean()) - mx * mx
                vy = float((yv * yv).mean()) - my * my
                cv = float((xv * yv).mean()) - mx * my
            else:
                sx = sy = sxx = syy = sxy = 0.0
                for i in idx:
                    a = xs[i]
                    b = ys[i]
                    sx += a
                    sy += b
                    sxx += a * a
                    syy += b * b
                    sxy += a * b
                mx = sx / m
                my = sy / m
                vx = sxx / m - mx * mx
                vy = syy / m - my * my
                cv = sxy / m - mx * my
            if vx < 0 and vx > -1e-12:
                vx = 0.0
            if vy < 0 and vy > -1e-12:
                vy = 0.0
            num = (2 * mx * my + c1) * (2 * cv + c2)
            den = (mx * mx + my * my + c1) * (vx + vy + c2)
            total += num / den if den else (1.0 if num == 0 else 0.0)
            count += 1
    return total / count if count else math.nan


def _ssim_channel(xs, ys, width, height, peak):
    if USE_NUMPY:
        import numpy as np
        return _ssim_tile_pass(np.asarray(xs, dtype=np.float64),
                               np.asarray(ys, dtype=np.float64),
                               width, height, np, peak)
    return _ssim_tile_pass(list(xs), list(ys), width, height, None, peak)


def cmd_metrics(args):
    try:
        channels, kind, bpc = parse_format(args.format)
        width = check_positive_int(args.width, "width")
        height = check_positive_int(args.height, "height")
        stride = None
        if args.stride is not None:
            stride = check_positive_int(args.stride, "stride")
        if args.peak is not None:
            peak = float(args.peak)
            if not math.isfinite(peak) or peak <= 0:
                raise ValueError("peak must be a finite value > 0")
        else:
            peak = default_peak(kind)
        cand = args.candidate.read_bytes()
        ref = args.reference.read_bytes()
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    try:
        xc = decode_values(cand, channels, kind, width, height, stride)
        xr = decode_values(ref, channels, kind, width, height, stride)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    lc = _to_list(xc)
    lr = _to_list(xr)
    for tag, vals in (("candidate", lc), ("reference", lr)):
        bad_nan = sum(1 for v in vals if math.isnan(v))
        bad_inf = sum(1 for v in vals if math.isinf(v))
        if bad_nan or bad_inf:
            print("error: %s contains %d NaN and %d Inf values; "
                  "PSNR/SSIM are undefined, fix the capture first"
                  % (tag, bad_nan, bad_inf), file=sys.stderr)
            return 2
    names = ("R", "G", "B", "A") if channels > 1 else ("C0",)
    pixels = width * height
    print("format: %s (%d channels x %s)" % (args.format, channels, kind))
    print("dimensions: %d x %d" % (width, height))
    print("peak: %r" % peak)
    print("ssim_window: box %dx%d non-overlapping "
          "(partial edge tiles included)" % (SSIM_WINDOW, SSIM_WINDOW))
    for c in range(channels):
        if USE_NUMPY:
            import numpy as np
            mc = xc.reshape(-1, channels)[:, c]
            mr = xr.reshape(-1, channels)[:, c]
            mse = float(((mc - mr) ** 2).mean())
            psnr = math.inf if mse == 0 else (
                20.0 * math.log10(peak) - 10.0 * math.log10(mse))
            ssim = _ssim_channel(mc, mr, width, height, peak)
        else:
            col_c = [lc[p * channels + c] for p in range(pixels)]
            col_r = [lr[p * channels + c] for p in range(pixels)]
            mse, psnr = _mse_psnr(col_c, col_r, peak)
            ssim = _ssim_channel(col_c, col_r, width, height, peak)
        label = names[c] if c < len(names) else ("C%d" % c)
        print("channel_%s_mse: %r" % (label, mse))
        print("channel_%s_psnr_db: %r" % (label, psnr))
        print("channel_%s_ssim: %r" % (label, ssim))
    lum_c = _luminance(xc, width, height, channels)
    lum_r = _luminance(xr, width, height, channels)
    if USE_NUMPY:
        import numpy as np
        la = np.asarray(lum_c, dtype=np.float64).ravel()
        lb = np.asarray(lum_r, dtype=np.float64).ravel()
        mse = float(((la - lb) ** 2).mean())
        psnr = math.inf if mse == 0 else (
            20.0 * math.log10(peak) - 10.0 * math.log10(mse))
    else:
        mse, psnr = _mse_psnr(list(lum_c), list(lum_r), peak)
    ssim = _ssim_channel(lum_c, lum_r, width, height, peak)
    print("luma_mse: %r" % mse)
    print("luma_psnr_db: %r" % psnr)
    print("luma_ssim: %r" % ssim)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="CPU-only comparison of raw GPU readback dumps.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="print sanity stats of one dump")
    p.add_argument("dump", type=Path)
    p.add_argument("--format", required=True)
    p.add_argument("--width", required=True)
    p.add_argument("--height", required=True)
    p.add_argument("--stride", default=None)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("diff", help="bitwise/tolerance diff of two dumps")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--tolerance", default="0.0")
    p.add_argument("--max-diffs", default=10)
    p.add_argument("--format", default=None)
    p.add_argument("--width", default=None)
    p.add_argument("--height", default=None)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("metrics", help="PSNR/SSIM of candidate vs reference")
    p.add_argument("candidate", type=Path)
    p.add_argument("reference", type=Path)
    p.add_argument("--format", required=True)
    p.add_argument("--width", required=True)
    p.add_argument("--height", required=True)
    p.add_argument("--stride", default=None)
    p.add_argument("--peak", default=None)
    p.set_defaults(func=cmd_metrics)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
