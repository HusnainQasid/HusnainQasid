#!/usr/bin/env python3
"""
embed_avatar.py -- swap the placeholder hologram avatar in banner.svg,
banner-light.svg, and lanyard.svg for your own cropped photo.

USAGE
    python3 scripts/embed_avatar.py path/to/your-photo.png

WHAT IT DOES
    1. Loads your image and makes a near-uniform background transparent
       (samples the four corners, then removes pixels close to that color).
       Works best with a clean/solid background; for a busy background,
       pre-cut the photo yourself in any editor and export a transparent
       PNG, then just skip straight to step 2 by re-running with that file.
    2. Crops to the visible (non-transparent) content, with a small margin.
    3. Base64-encodes the result as a PNG (GitHub-safe, no external file
       request, and it will not break if the repo is ever forked/cloned).
    4. Finds the "<!-- AVATAR_SLOT_START ... -->" ... "<!-- AVATAR_SLOT_END -->"
       block in each target SVG and replaces it with a single <image> tag
       sized to exactly fill that slot, so all the existing motion
       (holographic scanner sweep, swinging lanyard, glow ring, clip
       rounding) keeps working on top of your real photo.

    Re-run any time to swap the photo again -- it always replaces the
    slot fresh rather than stacking images.
"""
import sys
import re
import base64
import io
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install pillow --break-system-packages")

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    REPO_ROOT / "assets" / "banner.svg",
    REPO_ROOT / "assets" / "banner-light.svg",
    REPO_ROOT / "assets" / "lanyard.svg",
]

SLOT_RE = re.compile(
    r"<!-- AVATAR_SLOT_START (?P<attrs>[^>]*?) -->.*?<!-- AVATAR_SLOT_END -->",
    re.DOTALL,
)


def remove_background(img: Image.Image, tolerance: int = 28) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    out = Image.new("RGBA", (w, h))
    outpx = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            dist = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if dist < tolerance:
                outpx[x, y] = (r, g, b, 0)
            else:
                # soft-feather near the threshold so edges don't look cut out
                fade = min(1.0, (dist - tolerance) / (tolerance * 0.6 + 1e-6))
                outpx[x, y] = (r, g, b, int(a * max(0.0, min(1.0, fade + 0.55))))
    return out


def crop_to_content(img: Image.Image, margin_pct: float = 0.06) -> Image.Image:
    bbox = img.getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if y1 >= img.height - 10:
        y1 = int(y0 + h * 0.50)
        h = y1 - y0
    mx, my = int(w * margin_pct), int(h * margin_pct)
    x0, y0 = max(0, x0 - mx), max(0, y0 - my)
    x1, y1 = min(img.width, x1 + mx), min(img.height, y1 + my)
    return img.crop((x0, y0, x1, y1))


def pad_to_square(img: Image.Image) -> Image.Image:
    s = max(img.size)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(img, ((s - img.width) // 2, (s - img.height) // 2), img)
    return canvas


def to_base64_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_image_tag(b64: str, attrs: dict) -> str:
    if "cx" in attrs:  # circular slot (lanyard)
        cx, cy, r = float(attrs["cx"]), float(attrs["cy"]), float(attrs["r"])
        x, y, w, h = cx - r, cy - r, r * 2, r * 2
    else:  # rectangular slot (banner)
        x, y, w, h = (float(attrs["x"]), float(attrs["y"]),
                       float(attrs["w"]), float(attrs["h"]))
    return (f'<image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'preserveAspectRatio="xMidYMid slice" '
            f'href="data:image/png;base64,{b64}"/>')


def parse_attrs(attr_str: str) -> dict:
    return dict(pair.split("=") for pair in attr_str.split())


def patch_file(path: Path, b64: str) -> bool:
    if not path.exists():
        print(f"  skip (not found): {path}")
        return False
    svg = path.read_text()
    m = SLOT_RE.search(svg)
    if not m:
        print(f"  skip (no AVATAR_SLOT markers found): {path.name}")
        return False
    attrs = parse_attrs(m.group("attrs"))
    tag = build_image_tag(b64, attrs)
    new_block = f"<!-- AVATAR_SLOT_START {m.group('attrs')} -->{tag}<!-- AVATAR_SLOT_END -->"
    svg = svg[:m.start()] + new_block + svg[m.end():]
    path.write_text(svg)
    print(f"  updated: {path.relative_to(REPO_ROOT)}")
    return True


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python3 {sys.argv[0]} path/to/photo.png")
    src = Path(sys.argv[1])
    if not src.exists():
        sys.exit(f"File not found: {src}")

    print(f"Loading {src} ...")
    img = Image.open(src)
    print("Removing background (assumes a fairly clean/solid backdrop)...")
    img = remove_background(img)
    img = crop_to_content(img)
    img = pad_to_square(img)
    if img.width > 600:
        img = img.resize((600, 600), Image.LANCZOS)
    b64 = to_base64_png(img)
    print(f"Encoded as base64 PNG ({len(b64) // 1024} KB).")

    print("Patching SVGs:")
    any_ok = False
    for target in TARGETS:
        any_ok = patch_file(target, b64) or any_ok

    if any_ok:
        print("\nDone. Open the SVGs in a browser (or push to GitHub) to check the crop.")
        print("Re-run this script any time to try a different photo.")
    else:
        print("\nNothing was updated -- check the file paths in scripts/embed_avatar.py.")


if __name__ == "__main__":
    main()
