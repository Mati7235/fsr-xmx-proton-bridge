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


def similarity_mask(ref, alt, shift, threshold):
    a0 = max(0, shift)
    b0 = max(0, -shift)
    n = min(len(ref) - a0, len(alt) - b0)
    err = np.mean((ref[a0:a0 + n].astype(np.float32) -
                   alt[b0:b0 + n].astype(np.float32)) ** 2, axis=(1, 2))
    return a0, err < threshold


def longest_run(mask):
    best_start = best_len = cur_start = cur_len = 0
    for i, v in enumerate(mask):
        if v:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
        else:
            cur_len = 0
    return best_start, best_len


def motion_score(thumbs):
    """Mean absolute difference between consecutive thumbnails: high while the camera moves."""
    if len(thumbs) < 2:
        return np.zeros(0, dtype=np.float32)
    diff = np.abs(np.diff(thumbs.astype(np.int16), axis=0)).mean(axis=(1, 2))
    return diff.astype(np.float32)


def best_window(mask, motion, length, min_similar=0.9):
    """Window of `length` frames with the most moving seconds among similar frames.

    The benchmark moves the camera for its whole duration; menus and loading
    screens are static even when they look the same across runs. Counting
    moving seconds beats averaging, because a single hard cut would otherwise
    inflate the score of a window that includes the menu.
    """
    n = len(mask)
    length = min(length, n)
    threshold = max(1e-3, 0.2 * float(motion.max())) if len(motion) else 1.0
    best = None
    for start in range(0, n - length + 1):
        if mask[start:start + length].mean() < min_similar:
            continue
        seg = motion[start:start + length - 1]
        moving = float((seg > threshold).mean()) if len(seg) else 0.0
        mean = float(seg.mean()) if len(seg) else 0.0
        key = (moving, mean)
        if best is None or key > best[0]:
            best = (key, start, length)
    if best is None:
        return None
    return best[0][1], best[1], best[2]


def extract_frame(path, t, out_png):
    run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ss", f"{t:.3f}",
         "-frames:v", "1", out_png])
    return np.asarray(Image.open(out_png).convert("RGB"))


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

    # 1. Cada video: su propio bench es el tramo de `length` con mas movimiento.
    ref_move = motion_score(ref_thumbs)
    ref_win = best_window(np.ones(len(ref_thumbs), dtype=bool), ref_move, length)
    if ref_win is None:
        print("reference is too short for that --length", file=sys.stderr)
        return 2
    _, ref_start, ref_len = ref_win
    print(f"ref bench window: {ref_start}s .. {ref_start + ref_len}s")

    # 2. Alinear cada ventana contra la del referencia (solo dentro del bench).
    aligned = []
    for label, path in alts:
        thumbs = thumbnails(path)
        move = motion_score(thumbs)
        win = best_window(np.ones(len(thumbs), dtype=bool), move, length)
        if win is None:
            print(f"{label}: video too short for that --length", file=sys.stderr)
            return 2
        _, start, n = win
        shift, err = align_windows(ref_thumbs, ref_start, thumbs, start, min(ref_len, n))
        print(f"{label}: bench at {start}s, offset {shift:+d} s, window mse {err:.1f}")
        aligned.append((label, path, shift))

    if args.cmd == "align":
        return 0

    os.makedirs(args.out, exist_ok=True)
    start, run_len = ref_start, ref_len
    print(f"common window: {start}s .. {start + run_len}s ({run_len}s)")

    positions = [float(x) for x in args.positions.split(",") if x.strip()]
    crop = tuple(int(v) for v in args.crop.split(",")) if args.crop else None

    rows = []
    for p in positions:
        t = start + p * run_len
        frame_ref = extract_frame(args.ref, t, os.path.join(args.out, f"ref_{p:.2f}.png"))
        metrics = [("ref", None, None, sharpness(frame_ref))]
        images = [frame_ref]
        labels = ["reference (native)"]
        for label, path, shift in aligned:
            tt = t + shift
            frame = extract_frame(path, tt, os.path.join(args.out, f"{label}_{p:.2f}.png"))
            metrics.append((label, psnr(frame_ref, frame), ssim(frame_ref, frame), sharpness(frame)))
            images.append(frame)
            labels.append(label)
        if crop:
            side_by_side(images, labels, os.path.join(args.out, f"crop_{p:.2f}.png"), crop, zoom=2)
        rows.append((p, t, metrics))

    report = ["# Calidad por frame", "",
              f"Referencia: `{os.path.basename(args.ref)}`",
              f"Ventana comun: {start}s a {start + run_len}s", "",
              "| Posicion | t (s) | Muestra | PSNR vs ref | SSIM vs ref | Nitidez |",
              "|---|---:|---|---:|---:|---:|"]
    for p, t, metrics in rows:
        for label, ps, ss, sh in metrics:
            ps_txt = "-" if ps is None else f"{ps:.2f}"
            ss_txt = "-" if ss is None else f"{ss:.4f}"
            report.append(f"| {p:.2f} | {t:.1f} | {label} | {ps_txt} | {ss_txt} | {sh:.1f} |")
    report += ["", "Nitidez = varianza del Laplaciano sobre luma. Mas alto = mas detalle de alta frecuencia.",
               "PSNR/SSIM se calculan contra la referencia nativa, no entre upscalers."]
    path = os.path.join(args.out, "report.md")
    with open(path, "w") as f:
        f.write("\n".join(report) + "\n")
    print(f"reporte: {path}")
    for r in report[6:]:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
