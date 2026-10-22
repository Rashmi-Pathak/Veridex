"""Generate and register 15 varied sample images into Veridex.

Creates:
1. samples/original/ - high-quality original images with metadata
2. samples/stripped/ - re-encoded stripped images ready to drag and drop
3. web/public/samples/ - hosted in the Next.js public directory
4. Ingests all 15 into Veridex's PostgreSQL registry & Merkle transparency log.
"""

import hashlib
import io
import math
import os
from pathlib import Path
from dotenv import find_dotenv, load_dotenv
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import httpx

load_dotenv(find_dotenv(usecwd=True))

SAMPLES_DEF = [
    ("veridex-sample-01", "Cosmic Nebula", "gemini-2.5-flash", (20, 10, 45), (120, 40, 200)),
    ("veridex-sample-02", "Cyberpunk Grid", "stable-diffusion-3.5", (10, 30, 60), (0, 240, 180)),
    ("veridex-sample-03", "Solar Flare", "dall-e-3", (60, 10, 10), (255, 140, 0)),
    ("veridex-sample-04", "Emerald Forest", "midjourney-v6", (5, 40, 20), (50, 200, 100)),
    ("veridex-sample-05", "Alpine Dawn", "flux-1-schnell", (30, 40, 70), (240, 180, 120)),
    ("veridex-sample-06", "Oceanic Trench", "seedream-5.0", (0, 15, 35), (0, 140, 220)),
    ("veridex-sample-07", "Quantum Crystal", "gemini-2.5-flash", (40, 10, 50), (220, 80, 240)),
    ("veridex-sample-08", "Desert Mirage", "flux-1-dev", (70, 35, 15), (255, 210, 110)),
    ("veridex-sample-09", "Neon Tokyo", "stable-diffusion-xl", (25, 5, 40), (255, 0, 128)),
    ("veridex-sample-10", "Aurora Sky", "gemini-2.5-pro", (10, 25, 45), (40, 255, 160)),
    ("veridex-sample-11", "Golden Ratio Spiral", "imagen-3", (45, 30, 10), (255, 215, 0)),
    ("veridex-sample-12", "Obsidian Core", "dall-e-3", (15, 15, 20), (140, 140, 160)),
    ("veridex-sample-13", "Bioluminescent Reef", "flux-1-schnell", (5, 20, 40), (0, 255, 230)),
    ("veridex-sample-14", "Retro Synthwave Sunset", "stable-diffusion-3.5", (35, 5, 50), (255, 90, 50)),
    ("veridex-sample-15", "Deep Space Pulsar", "gemini-2.5-flash", (5, 5, 25), (180, 200, 255)),
]


def generate_artistic_image(seed_idx: int, title: str, c1: tuple, c2: tuple) -> Image.Image:
    w, h = 512, 512
    img = Image.new("RGB", (w, h), color=c1)
    draw = ImageDraw.Draw(img)

    # 1. Gradient background
    for y in range(h):
        ratio = y / h
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # 2. Geometric / orbital circles & rings
    cx, cy = w // 2, h // 2
    for r in range(40, 220, 30):
        alpha_color = (
            (c2[0] + r * 2) % 256,
            (c2[1] + r * 3) % 256,
            (c2[2] + r * 4) % 256,
        )
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=alpha_color, width=3)

    # 3. Polygon and star bursts
    rng = np.random.default_rng(seed_idx + 42)
    for _ in range(12):
        x = rng.integers(50, w - 50)
        y = rng.integers(50, h - 50)
        rad = rng.integers(15, 60)
        poly_color = (
            rng.integers(100, 255),
            rng.integers(100, 255),
            rng.integers(100, 255),
        )
        points = [
            (x + int(rad * math.cos(2 * math.pi * k / 6)), y + int(rad * math.sin(2 * math.pi * k / 6)))
            for k in range(6)
        ]
        draw.polygon(points, outline=poly_color, width=2)

    # 4. Subtle blur to give photographic depth
    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    return img


def main():
    out_dir = Path("samples")
    orig_dir = out_dir / "original"
    strip_dir = out_dir / "stripped"
    pub_dir = Path("web/public/samples")

    orig_dir.mkdir(parents=True, exist_ok=True)
    strip_dir.mkdir(parents=True, exist_ok=True)
    pub_dir.mkdir(parents=True, exist_ok=True)

    ingest_key = os.environ.get("VERIDEX_INGEST_KEY", "")
    headers = {
        "X-Ingest-Key": ingest_key,
        "X-Veridex-Ingest-Key": ingest_key,
    }

    print(f"Starting generation and registration of {len(SAMPLES_DEF)} images...")
    print(f"Using ingest key (length={len(ingest_key)})")

    results = []
    with httpx.Client(timeout=30.0) as client:
        for idx, (sample_id, title, model, c1, c2) in enumerate(SAMPLES_DEF, start=1):
            manifest_id = f"urn:c2pa:{sample_id}"
            watermark_id = f"VDX{idx:02d}"

            # 1. Generate image
            img = generate_artistic_image(idx, title, c1, c2)

            # Save original JPEG
            orig_path = orig_dir / f"{sample_id}.jpg"
            img.save(orig_path, "JPEG", quality=95)
            img.save(pub_dir / f"{sample_id}.jpg", "JPEG", quality=95)

            # Save stripped JPEG (re-encoded at lower quality, dropping all metadata)
            strip_path = strip_dir / f"{sample_id}_stripped.jpg"
            img.save(strip_path, "JPEG", quality=80)
            img.save(pub_dir / f"{sample_id}_stripped.jpg", "JPEG", quality=80)

            # 2. Ingest original image into Veridex
            data = orig_path.read_bytes()
            files = {"file": (f"{sample_id}.jpg", data, "image/jpeg")}
            form = {
                "manifest_id": manifest_id,
                "watermark_id": watermark_id,
                "model": model,
                "returnReceipt": "true",
            }

            resp = client.post("http://localhost:8000/ingest", headers=headers, data=form, files=files)
            if resp.status_code in (200, 201):
                status_str = "INGESTED OK"
            elif resp.status_code == 409:
                status_str = "ALREADY REGISTERED"
            else:
                status_str = f"FAILED ({resp.status_code}: {resp.text})"

            # 3. Test recovery of stripped copy
            stripped_data = strip_path.read_bytes()
            test_files = {"file": ("stripped.jpg", stripped_data, "image/jpeg")}
            match_resp = client.post("http://localhost:8000/matches/byContent", files=test_files)
            match_data = match_resp.json()
            matches = match_data.get("matches", [])
            top_match = matches[0] if matches else None
            score = top_match.get("similarityScore") if top_match else 0
            recovered = top_match.get("manifestId") == manifest_id if top_match else False

            results.append((sample_id, title, model, status_str, recovered, score))
            print(f"[{idx:02d}/{len(SAMPLES_DEF)}] {title} -> Ingest: {status_str} | Stripped Match: {recovered} (Score: {score}/100)")

    print("\n=== SUMMARY OF REGISTERED SAMPLES ===")
    for sid, title, model, status_str, rec, score in results:
        status_icon = "[OK]" if rec else "[FAIL]"
        print(f" {status_icon} {sid}: {title} [{model}] - Match score: {score}/100")


if __name__ == "__main__":
    main()
