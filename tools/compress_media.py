"""Recompress atlas animations so the published site stays small.

Every animated WebP is cut to its last full flap cycle (the period is detected
from the frames themselves, so no cycle count is assumed), downscaled, and
re-encoded. The result loops seamlessly. Still images and other files are
copied unchanged. Original full-length media stay in the local archive.

    python tools/compress_media.py SOURCE_MEDIA_DIR atlas/media [--workers 8]

Only files referenced by the atlas data need to be published; pass
--only-referenced atlas/data to skip the rest.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence

MAX_WIDTH = 800
QUALITY = 60


def detect_period(frames: list[np.ndarray], min_lag: int = 10) -> int | None:
    """Smallest lag at which the last part of the clip repeats itself."""
    n = len(frames)
    if n < 2 * min_lag:
        return None
    small = np.stack(frames).astype(np.float32)
    errs = {}
    for lag in range(min_lag, n // 2 + 1):
        a = small[n - lag:]           # last `lag` frames
        b = small[n - 2 * lag:n - lag]  # the `lag` frames before them
        errs[lag] = float(np.mean(np.abs(a - b)))
    best = min(errs.values())
    # first lag whose error is close to the best (avoids picking 2x the period)
    tol = best * 1.5 + 0.5
    for lag in sorted(errs):
        if errs[lag] <= tol:
            return lag
    return None


MAIN_VIEWS = ("main.webp", "animation.webp")
SIBLING_OF = {"front.webp": "main.webp", "top.webp": "main.webp",
              "animation_front.webp": "animation.webp", "animation_top.webp": "animation.webp"}
NO_TRIM = ("montage.webp",)  # side-by-side composites: downscale only


def compress(src: Path, dst: Path, period: int | None = None, trim: bool = True) -> dict:
    im = Image.open(src)
    n = getattr(im, "n_frames", 1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if n <= 1:
        shutil.copy2(src, dst)
        return {"file": str(dst), "frames_in": n, "frames_out": n, "copied": True}
    frames, durations, thumbs = [], [], []
    for f in ImageSequence.Iterator(im):
        durations.append(f.info.get("duration", 40) or 40)
        rgba = f.convert("RGBA")
        frames.append(rgba.copy())
        thumbs.append(np.asarray(rgba.convert("L").resize((80, 60))))
    # Front/top views reuse the side view's period: seen from above, up- and down-strokes
    # can look alike and the detector would lock onto half a cycle.
    lag = (period or detect_period(thumbs)) if trim else None
    keep = frames[-lag:] if lag and lag < n else frames
    scale = min(1.0, MAX_WIDTH / keep[0].width)
    size = (round(keep[0].width * scale), round(keep[0].height * scale))
    out = [f.resize(size, Image.LANCZOS) if scale < 1 else f for f in keep]
    dur = int(np.median(durations[-len(keep):]))
    out[0].save(dst, save_all=True, append_images=out[1:], quality=QUALITY, method=4, duration=dur, loop=0)
    return {"file": str(dst), "frames_in": n, "frames_out": len(out), "period": lag,
            "bytes_in": src.stat().st_size, "bytes_out": dst.stat().st_size}


def referenced(data_dir: Path) -> set[str]:
    refs: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and "/" in o and o.rsplit(".", 1)[-1] in ("webp", "png", "gif", "json", "jpg"):
            refs.add(o)

    for p in data_dir.rglob("*.json"):
        if p.parent.name == "rows":
            continue
        walk(json.loads(p.read_text(encoding="utf-8")))
    return refs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only-referenced", type=Path, help="atlas data folder; publish only media it references")
    args = ap.parse_args(argv)
    files = [p for p in args.source.rglob("*") if p.is_file()]
    if args.only_referenced:
        refs = referenced(args.only_referenced)
        files = [p for p in files if p.relative_to(args.source).as_posix() in refs]
    pending = []
    for p in files:
        dst = args.dest / p.relative_to(args.source)
        if dst.exists() and dst.stat().st_mtime >= p.stat().st_mtime:
            continue
        if p.suffix.lower() != ".webp":
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        else:
            pending.append((p, dst))
    periods: dict[Path, int | None] = {}
    log = []

    def run(batch, ex):
        futs = {}
        for p, dst in batch:
            sib = SIBLING_OF.get(p.name)
            period = periods.get(p.parent / sib) if sib else None
            futs[ex.submit(compress, p, dst, period, p.name not in NO_TRIM)] = p
        for fut in as_completed(futs):
            r = fut.result()
            periods[futs[fut]] = r.get("period")
            log.append(r)
            print(f"[{len(log)}/{len(pending)}] {r.get('frames_in')}->{r.get('frames_out')} frames, "
                  f"period {r.get('period')}, {r.get('bytes_out', 0) / 1e6:.2f} MB  {r['file']}", flush=True)

    with ProcessPoolExecutor(args.workers) as ex:
        run([j for j in pending if j[0].name in MAIN_VIEWS], ex)        # side views first
        run([j for j in pending if j[0].name not in MAIN_VIEWS], ex)    # then siblings, reusing periods
    total = sum(p.stat().st_size for p in args.dest.rglob("*") if p.is_file())
    print(f"done: {len(pending)} animations recompressed; {args.dest} is {total / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
