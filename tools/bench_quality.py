#!/usr/bin/env python3
"""Compare upscalers frame by frame against a native reference recording.

Takes lossless recordings of the same deterministic benchmark (Cyberpunk's
built-in one), aligns them by content, extracts matching frames, and reports
sharpness plus PSNR/SSIM against the reference, with side-by-side crops.

Requires ffmpeg, numpy and Pillow. Read-only on the recordings.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

THUMB_W, THUMB_H = 48, 27


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def video_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path]).stdout.decode().strip()
    return float(out)


def thumbnails(path, fps=1):
    """Grayscale thumbnails, one per second, as uint8 [n, H, W]."""
    raw = run(["ffmpeg", "-v", "error", "-i", path,
               "-vf", f"fps={fps},scale={THUMB_W}:{THUMB_H},format=gray",
               "-f", "rawvideo", "-"]).stdout
    size = THUMB_W * THUMB_H
    n = len(raw) // size
    return np.frombuffer(raw[:n * size], dtype=np.uint8).reshape(n, THUMB_H, THUMB_W)


def best_common_window(ref, alt, length):
    """Find the ref window and offset where both recordings match best.

    The benchmark is the same camera path in every run, so it is the segment
    that matches across recordings. Menus have animated backgrounds that are
    not synchronized, and loading screens differ, so they match worse even
    when they move more.

    Returns (mean_mse, ref_start, offset) with alt index = ref index + offset.
    """
    n1, n2 = len(ref), len(alt)
    length = min(length, n1, n2)
    R = ref.reshape(n1, -1).astype(np.float32)
    A = alt.reshape(n2, -1).astype(np.float32)
    best = None
    for offset in range(-(n1 - length), n2 - length + 1):
        i0 = max(0, -offset)
        i1 = min(n1 - length, n2 - length - offset)
        if i1 < i0:
            continue
        idx = np.arange(i0, i1 + length)
        diff = R[idx] - A[idx + offset]
        diag = (diff * diff).mean(axis=1)
        c = np.concatenate(([0.0], np.cumsum(diag, dtype=np.float64)))
        sums = c[length:] - c[:-length]
        k = int(np.argmin(sums))
        value = float(sums[k] / length)
        if best is None or value < best[0]:
            best = (value, i0 + k, offset)
    return best


def align_windows(ref, ref_start, alt, alt_start, length, search=20):
    """Offset (seconds) that best matches alt's window onto the reference's window."""
    best_shift, best_err = 0, None
    for shift in range(-search, search + 1):
        b0 = alt_start + shift
        if b0 < 0:
            continue
        n = min(length, len(ref) - ref_start, len(alt) - b0)
        if n < max(5, length // 2):
            continue
        err = np.mean((ref[ref_start:ref_start + n].astype(np.float32) -
                       alt[b0:b0 + n].astype(np.float32)) ** 2)
        if best_err is None or err < best_err:
            best_shift, best_err = shift, err
    return best_shift, (best_err if best_err is not None else float("nan"))


def align(ref, alt, max_shift=240):
    """Shift (in thumbnail frames) that best matches alt onto ref."""
    min_overlap = max(5, min(len(ref), len(alt)) // 2)
    limit = min(max_shift, len(ref) - min_overlap, len(alt) - min_overlap)
    best, best_err = 0, None
    for shift in range(-limit, limit + 1):
        a0 = max(0, shift)
        b0 = max(0, -shift)
        n = min(len(ref) - a0, len(alt) - b0)
        if n < min_overlap:
            continue
        err = np.mean((ref[a0:a0 + n].astype(np.float32) -
                       alt[b0:b0 + n].astype(np.float32)) ** 2)
        if best_err is None or err < best_err:
            best, best_err = shift, err
    return best, (best_err if best_err is not None else float("nan"))


def extract_frame(path, t, out_png):
    # Input seeking jumps to the keyframe and decodes only up to t; output
    # seeking would decode the whole recording for every sample.
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path,
         "-frames:v", "1", out_png])
    return np.asarray(Image.open(out_png).convert("RGB"))


MATCH_W, MATCH_H = 320, 180


def raw_frames(path, t, count, fps=60):
    """`count` RGB frames from t, downscaled for matching."""
    raw = run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
               "-vf", f"fps={fps},scale={MATCH_W}:{MATCH_H}:flags=area,format=rgb24",
               "-frames:v", str(count), "-f", "rawvideo", "-"]).stdout
    size = MATCH_W * MATCH_H * 3
    n = len(raw) // size
    return np.frombuffer(raw[:n * size], dtype=np.uint8).reshape(n, MATCH_H, MATCH_W, 3)


def best_offset(ref_frame, alt_frames, fps, radius):
    """Seconds to add to the alt time so it matches ref_frame.

    alt_frames[0] is assumed to be at (t - radius); the returned offset is
    k/fps - radius for the best matching frame k.
    """
    diff = alt_frames.astype(np.float32) - ref_frame.astype(np.float32)
    mse = (diff * diff).mean(axis=tuple(range(1, diff.ndim)))
    k = int(np.argmin(mse))
    return k / fps - radius


def fine_offset(ref_path, alt_path, times, base_shift=0.0, radius=0.3, fps=60):
    """Median sub-second offset of alt against ref at the given ref times.

    A one-second alignment leaves up to half a second of error, which on a
    moving camera is a completely different frame. This measures at 60 fps
    around the coarse shift and returns the median.
    """
    count = int(round(2 * radius * fps)) + 1
    offsets = []
    for t in times:
        start = t + base_shift - radius
        if t < 0 or start < 0:
            continue
        ref_frame = raw_frames(ref_path, t, 1, fps)[0]
        alt_frames = raw_frames(alt_path, start, count, fps)
        if len(alt_frames) < 3:
            continue
        offsets.append(best_offset(ref_frame, alt_frames, fps, radius))
    return float(np.median(offsets)) if offsets else 0.0


def luma(img):
    return (0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2])


def sharpness(img):
    """Variance of the Laplacian on luma: higher means more high-frequency detail."""
    y = luma(img).astype(np.float32)
    lap = (4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:])
    return float(lap.var())


def psnr(a, b):
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    if mse == 0:
        return float("inf")
    return float(10 * np.log10((255.0 ** 2) / mse))


def ssim(a, b):
    """Global SSIM on luma (not windowed), enough for a relative comparison."""
    x = luma(a).astype(np.float64)
    y = luma(b).astype(np.float64)
    ux, uy = x.mean(), y.mean()
    vx, vy = x.var(), y.var()
    cxy = ((x - ux) * (y - uy)).mean()
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    return float(((2 * ux * uy + c1) * (2 * cxy + c2)) /
                 ((ux ** 2 + uy ** 2 + c1) * (vx + vy + c2)))


def side_by_side(images, labels, out_png, crop=None, zoom=2):
    tiles = []
    for img, label in zip(images, labels):
        if crop:
            x, y, w, h = crop
            img = img[y:y + h, x:x + w]
        im = Image.fromarray(img)
        if zoom != 1:
            im = im.resize((im.width * zoom, im.height * zoom), Image.NEAREST)
        canvas = Image.new("RGB", (im.width, im.height + 28), (16, 16, 16))
        canvas.paste(im, (0, 28))
        ImageDraw.Draw(canvas).text((8, 8), label, fill=(255, 255, 255))
        tiles.append(canvas)
    total_w = sum(t.width for t in tiles)
    out = Image.new("RGB", (total_w, max(t.height for t in tiles)), (16, 16, 16))
    x = 0
    for t in tiles:
        out.paste(t, (x, 0))
        x += t.width
    out.save(out_png)
    return out_png


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_align = sub.add_parser("align", help="print the time offset of each video against the reference")
    p_align.add_argument("--ref", required=True)
    p_align.add_argument("--alt", action="append", required=True, help="label=path")
    p_align.add_argument("--length", type=float, default=64.0,
                         help="seconds of benchmark to look for (default 64)")

    p_rep = sub.add_parser("report", help="align, extract frames and compare")
    p_rep.add_argument("--ref", required=True, help="native reference recording")
    p_rep.add_argument("--alt", action="append", required=True, help="label=path")
    p_rep.add_argument("--out", required=True, help="output directory")
    p_rep.add_argument("--positions", default="0.15,0.35,0.55,0.75,0.9")
    p_rep.add_argument("--length", type=float, default=64.0,
                       help="seconds of benchmark to look for (default 64, Cyberpunk's is 64.2); 0 disables")
    p_rep.add_argument("--crop", default="", help="x,y,w,h in source pixels")
    p_rep.add_argument("--similarity", type=float, default=120.0,
                       help="max mean squared error on thumbnails to consider the same scene")
    args = ap.parse_args()

    alts = []
    for spec in args.alt:
        if "=" not in spec:
            ap.error("--alt needs label=path")
        label, path = spec.split("=", 1)
        alts.append((label, path))

    ref_thumbs = thumbnails(args.ref)
    length = int(round(args.length)) if args.length > 0 else 64
    print(f"ref: {os.path.basename(args.ref)} ({len(ref_thumbs)} s)")

    # 1. Para cada video, el bench es el tramo que mejor coincide entre
    #    corridas: la camara hace el mismo recorrido. Menus y cargas no
    #    coinciden aunque tengan mas movimiento.
    found = []
    for label, path in alts:
        thumbs = thumbnails(path)
        value, ref_start, offset = best_common_window(ref_thumbs, thumbs, length)
        print(f"{label}: match mse {value:.1f}, ref start {ref_start}s, offset {offset:+d} s")
        found.append((label, path, thumbs, value, ref_start, offset))

    if args.cmd == "align":
        return 0

    # Ventana de referencia: la mediana de las detectadas, para que un video
    # raro no la arrastre. Se avisa si no coinciden.
    starts = sorted(f[4] for f in found)
    ref_start = starts[len(starts) // 2]
    if starts[-1] - starts[0] > 5:
        print(f"aviso: las ventanas detectadas no coinciden ({starts}); uso {ref_start}s")

    aligned = []
    samples = [ref_start + q * length for q in (0.25, 0.5, 0.75)]
    for label, path, thumbs, value, alt_start, offset in found:
        shift, err = align_windows(ref_thumbs, ref_start, thumbs, ref_start + offset, length)
        fine = fine_offset(args.ref, path, samples, base_shift=shift)
        print(f"{label}: offset {shift:+d} s, ajuste fino {fine:+.3f} s, window mse {err:.1f}")
        aligned.append((label, path, shift + fine))

    os.makedirs(args.out, exist_ok=True)
    start, run_len = ref_start, length
    print(f"common window: {start}s .. {start + run_len}s ({run_len}s)")

    positions = [float(x) for x in args.positions.split(",") if x.strip()]
    crop = tuple(int(v) for v in args.crop.split(",")) if args.crop else None

    rows = []
    for p in positions:
        t = start + p * run_len
        frame_ref = extract_frame(args.ref, t, os.path.join(args.out, f"ref_{p:.2f}.png"))
        metrics = [("ref", None, None, sharpness(frame_ref), None, None)]
        images = [frame_ref]
        labels = ["reference (native)"]
        for label, path, shift in aligned:
            tt = t + shift
            frame = extract_frame(path, tt, os.path.join(args.out, f"{label}_{p:.2f}.png"))
            # Full-frame PSNR/SSIM pay for pedestrians and vehicles that are
            # not in the same place across runs; the crop is usually static and
            # is where the detail being judged actually lives.
            cps = css = None
            if crop:
                x, y, w, h = crop
                cps = psnr(frame_ref[y:y + h, x:x + w], frame[y:y + h, x:x + w])
                css = ssim(frame_ref[y:y + h, x:x + w], frame[y:y + h, x:x + w])
            metrics.append((label, psnr(frame_ref, frame), ssim(frame_ref, frame),
                            sharpness(frame), cps, css))
            images.append(frame)
            labels.append(label)
        if crop:
            side_by_side(images, labels, os.path.join(args.out, f"crop_{p:.2f}.png"), crop, zoom=2)
        rows.append((p, t, metrics))

    report = ["# Calidad por frame", "",
              f"Referencia: `{os.path.basename(args.ref)}`",
              f"Ventana comun: {start}s a {start + run_len}s", "",
              "| Posicion | t (s) | Muestra | PSNR vs ref | SSIM vs ref | PSNR crop | SSIM crop | Nitidez |",
              "|---|---:|---|---:|---:|---:|---:|---:|"]
    for p, t, metrics in rows:
        for label, ps, ss, sh, cps, css in metrics:
            ps_txt = "-" if ps is None else f"{ps:.2f}"
            ss_txt = "-" if ss is None else f"{ss:.4f}"
            cps_txt = "-" if cps is None else f"{cps:.2f}"
            css_txt = "-" if css is None else f"{css:.4f}"
            report.append(f"| {p:.2f} | {t:.1f} | {label} | {ps_txt} | {ss_txt} | "
                          f"{cps_txt} | {css_txt} | {sh:.1f} |")
    report += ["", "Nitidez = varianza del Laplaciano sobre luma. Mas alto = mas detalle de alta frecuencia.",
               "PSNR/SSIM se calculan contra la referencia nativa, no entre upscalers.",
               "PSNR/SSIM crop usan solo la region del crop, sin peatones ni vehiculos en movimiento."]
    path = os.path.join(args.out, "report.md")
    with open(path, "w") as f:
        f.write("\n".join(report) + "\n")
    print(f"reporte: {path}")
    for r in report[6:]:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
