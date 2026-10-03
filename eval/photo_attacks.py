"""Generate attacked variants of every photo, and the photo manifest.

Every attack in ATTACKS is applied to every photo in eval/photos.csv, originals and negatives
alike, producing eval/data/photo_variants/<photo_id>__<attack>.jpg. Existing variants are
skipped, but each still gets a manifest row, as in eval/attacks.py.

Manifest (eval/data/photo_manifest.csv): variant_path, photo_id, original_id, attack, params,
split. original_id is the photo_id for variants of an original and empty for negatives.
"""

import csv
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from eval.attacks import CAPTIONS, LOGO_STYLES, logo_png, text_png
from eval.photos import EVAL_DIR, Photo, load_photos
from eval.photos import OUT_DIR as PHOTOS_DIR

SEED = 1
DATA_DIR = EVAL_DIR / "data"
VARIANTS_DIR = DATA_DIR / "photo_variants"
MANIFEST = DATA_DIR / "photo_manifest.csv"

# JPEG quality for every variant unless an attack sets its own.
DEFAULT_QUALITY = 90

# Border colours for pad, in OpenCV's BGR order.
PAD_COLOURS = {"white": (255, 255, 255), "black": (0, 0, 0), "grey": (128, 128, 128)}

# Filler photos for collage: the "unrelated" negatives, which are in no near-duplicate group.
COLLAGE_FILLERS = ["photo_357", "photo_312", "photo_23", "photo_24"]


@dataclass(frozen=True)
class PhotoVariant:
    image: np.ndarray  # BGR, uint8, as OpenCV loads it
    params: dict[str, object]  # recorded in the manifest; include every random choice
    quality: int = DEFAULT_QUALITY


# An attack gets its own copy of the photo's pixels and a random generator seeded for this
# (photo, attack) pair only.
PhotoAttack = Callable[[np.ndarray, random.Random], PhotoVariant]


# --- Examples ---------------------------------------------------------------------------


def recompress(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Heavy JPEG compression with visible blocking."""
    return PhotoVariant(img, {"quality": 30}, quality=30)


def mirror(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Flip left to right."""
    return PhotoVariant(cv2.flip(img, 1), {})


# --- Attacks ----------------------------------------------------------------------------


def resize(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Shrink so the long side is 480 pixels, keeping the aspect ratio.

    One scale factor from the longer side, so portrait photos shrink as much as landscape
    ones. cv2.resize takes (width, height); img.shape is (height, width, channels).
    """
    h, w = img.shape[:2]
    scale = 480 / max(h, w)
    size = (round(w * scale), round(h * scale))
    return PhotoVariant(cv2.resize(img, size, interpolation=cv2.INTER_AREA), {"long_side": 480})


def pad(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Add a plain border: an even frame, or padding the short sides out to a square.

    The square mode mimics posting a non-square photo to a square-only feed. Sizes are
    relative to the photo, so large and small photos get proportionally similar borders.
    """
    h, w = img.shape[:2]
    colour = rng.choice(list(PAD_COLOURS))
    mode = rng.choice(["frame", "square"])
    if mode == "frame":
        share = round(rng.uniform(0.03, 0.12), 3)
        b = round(share * max(h, w))
        top = bottom = left = right = b
        params = {"mode": mode, "share": share, "pixels": b, "colour": colour}
    else:
        extra = abs(h - w)
        top, left = (extra // 2, 0) if w > h else (0, extra // 2)
        bottom, right = (extra - top, 0) if w > h else (0, extra - left)
        params = {"mode": mode, "colour": colour}
    out = cv2.copyMakeBorder(
        img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=PAD_COLOURS[colour]
    )
    return PhotoVariant(out, params)


def crop(img: np.ndarray, rng: random.Random, fraction: float) -> PhotoVariant:
    """Cut away `fraction` of the width and height at a random position.

    x and y are the left and top edges as shares of the photo; keeping them at most
    `fraction` keeps the window inside the picture.
    """
    h, w = img.shape[:2]
    keep = 1 - fraction
    ch, cw = round(h * keep), round(w * keep)
    x = round(rng.uniform(0, fraction), 3)
    y = round(rng.uniform(0, fraction), 3)
    left, top = min(round(x * w), w - cw), min(round(y * h), h - ch)
    return PhotoVariant(
        img[top : top + ch, left : left + cw], {"fraction": fraction, "x": x, "y": y}
    )


def brightness_contrast(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Lighten or darken with gamma, plus a mild contrast change; same ranges as the video.

    A 256-entry lookup table maps every input level to its output level, so the whole photo
    is transformed by one table lookup per pixel. Contrast stretches around mid-grey; gamma
    above 1 lightens, matching ffmpeg's eq filter used for the video attack.
    """
    if rng.random() < 0.5:
        gamma = round(rng.uniform(0.85, 0.93), 2)  # darker
    else:
        gamma = round(rng.uniform(1.08, 1.25), 2)  # lighter
    contrast = round(rng.uniform(0.9, 1.1), 2)
    levels = np.arange(256) / 255
    levels = np.clip((levels - 0.5) * contrast + 0.5, 0, 1) ** (1 / gamma)
    lut = np.round(levels * 255).astype(np.uint8)
    return PhotoVariant(cv2.LUT(img, lut), {"gamma": gamma, "contrast": contrast})


def paste_png(
    img: np.ndarray, png: Path, width: float, x: float, y: float, opacity: float = 1.0
) -> np.ndarray:
    """Return a copy of img with a transparent PNG pasted on it.

    width is the PNG's width as a share of the image's. x and y place it within the free
    space: 0 is the left or top edge, 1 the right or bottom edge, so it always fits.
    opacity scales the PNG's own transparency.
    """
    overlay = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)  # keeps the alpha channel: BGRA
    H, W = img.shape[:2]
    w = min(W, max(1, round(W * width)))
    h = min(H, max(1, round(overlay.shape[0] * w / overlay.shape[1])))
    overlay = cv2.resize(overlay, (w, h), interpolation=cv2.INTER_AREA)
    left, top = round(x * (W - w)), round(y * (H - h))

    # out = alpha * overlay + (1 - alpha) * background, per pixel, in float.
    alpha = overlay[..., 3:4].astype(np.float32) / 255 * opacity
    region = img[top : top + h, left : left + w].astype(np.float32)
    blended = alpha * overlay[..., :3].astype(np.float32) + (1 - alpha) * region
    out = img.copy()
    out[top : top + h, left : left + w] = np.round(blended).astype(np.uint8)
    return out


def text_overlay(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """A caption burned into the photo, like a re-poster's account name."""
    text = rng.choice(CAPTIONS)
    width = round(rng.uniform(0.2, 0.35), 3)
    x = round(rng.uniform(0.05, 0.95), 3)
    edge = rng.choice(["top", "bottom"])
    y = round(rng.uniform(0.03, 0.1) if edge == "top" else rng.uniform(0.9, 0.97), 3)
    out = paste_png(img, text_png(text), width, x, y)
    return PhotoVariant(out, {"text": text, "width": width, "x": x, "y": y})


def logo_overlay(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """A semi-transparent watermark near a corner; same choices as the video attack."""
    style = rng.choice(LOGO_STYLES)
    corner = rng.choice(["top_left", "top_right", "bottom_left", "bottom_right"])
    width = round(rng.uniform(0.08, 0.15), 3)
    inset = round(rng.uniform(0.02, 0.05), 3)
    opacity = round(rng.uniform(0.4, 0.7), 2)
    x = inset if corner.endswith("left") else 1 - inset
    y = inset if corner.startswith("top") else 1 - inset
    out = paste_png(img, logo_png(style), width, x, y, opacity)
    params = {"style": style, "corner": corner, "width": width, "inset": inset, "opacity": opacity}
    return PhotoVariant(out, params)


def rotate_small(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Rotate by 3-15 degrees either way, as when a photo is re-shot or straightened by hand.

    The photo is zoomed just enough that the rotated picture fills the whole frame. Black
    corners would be sharp, artificial edges that real copies don't have, and a matcher
    could learn to rely on them.
    """
    h, w = img.shape[:2]
    angle = round(rng.choice([-1, 1]) * rng.uniform(3, 15), 2)
    t = np.radians(abs(angle))
    # Smallest zoom at which the rotated w x h picture still covers the w x h frame.
    scale = np.cos(t) + np.sin(t) * max(w / h, h / w)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    out = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return PhotoVariant(out, {"angle": angle, "scale": round(float(scale), 3)})


def rotate_90(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """Quarter turn, as when orientation metadata is lost or ignored."""
    direction = rng.choice(["clockwise", "anticlockwise"])
    code = cv2.ROTATE_90_CLOCKWISE if direction == "clockwise" else cv2.ROTATE_90_COUNTERCLOCKWISE
    return PhotoVariant(cv2.rotate(img, code), {"direction": direction})


def fill(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale img to cover w x h, then crop the centre to exactly w x h."""
    scale = max(w / img.shape[1], h / img.shape[0])
    big = cv2.resize(
        img, (max(w, round(img.shape[1] * scale)), max(h, round(img.shape[0] * scale)))
    )
    top, left = (big.shape[0] - h) // 2, (big.shape[1] - w) // 2
    return big[top : top + h, left : left + w]


def collage(img: np.ndarray, rng: random.Random) -> PhotoVariant:
    """The photo as one tile of a 2x2 collage among unrelated photos (measured only).

    Fillers come only from COLLAGE_FILLERS, never from catalog originals, so a variant never
    contains two originals. A filler that is this very photo is skipped.
    """
    h, w = img.shape[:2]
    tw, th = w // 2, h // 2
    gap = max(2, round(0.01 * w))
    fillers = [f for f in COLLAGE_FILLERS if not np.array_equal(load(f), img)]
    chosen = rng.sample(fillers, 3)
    tile = rng.randrange(4)
    tiles = [load(f) for f in chosen]
    tiles.insert(tile, img)

    canvas = np.full((2 * th + 3 * gap, 2 * tw + 3 * gap, 3), 255, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, 2)
        top, left = gap + r * (th + gap), gap + c * (tw + gap)
        canvas[top : top + th, left : left + tw] = fill(t, tw, th)
    return PhotoVariant(canvas, {"grid": "2x2", "tile": tile, "fillers": chosen})


# fmt: off
ATTACKS: dict[str, PhotoAttack] = {
    "recompress":          recompress,
    "resize_480":          resize,
    "pad":                 pad,
    "mirror":              mirror,
    "crop_10":             lambda i, r: crop(i, r, 0.10),
    "crop_20":             lambda i, r: crop(i, r, 0.20),
    "crop_35":             lambda i, r: crop(i, r, 0.35),
    "brightness_contrast": brightness_contrast,
    "text_overlay":        text_overlay,
    "logo_overlay":        logo_overlay,
    "rotate_small":        rotate_small,
    "rotate_90":           rotate_90,
    "collage":             collage,
}
# fmt: on


# --- Plumbing ---------------------------------------------------------------------------


def load(photo_id: str) -> np.ndarray:
    img = cv2.imread(str(PHOTOS_DIR / f"{photo_id}.jpg"), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"{photo_id}: run `just photos` first")
    return img


def write(variant: PhotoVariant, dst: Path) -> None:
    img = variant.image
    if img.dtype != np.uint8 or img.ndim != 3 or img.shape[2] != 3:
        raise ValueError(f"{dst.name}: expected a BGR uint8 image, got {img.dtype} {img.shape}")
    if min(img.shape[:2]) < 32:
        raise ValueError(f"{dst.name}: implausibly small ({img.shape[1]}x{img.shape[0]})")
    tmp = dst.with_suffix(".tmp.jpg")
    if not cv2.imwrite(str(tmp), img, [cv2.IMWRITE_JPEG_QUALITY, variant.quality]):
        raise OSError(f"{dst.name}: could not write")
    tmp.rename(dst)


def manifest_row(photo: Photo, attack: str, dst: Path, variant: PhotoVariant) -> dict[str, str]:
    return {
        "variant_path": str(dst.relative_to(DATA_DIR)),
        "photo_id": photo.photo_id,
        "original_id": photo.photo_id if photo.role == "original" else "",
        "attack": attack,
        "params": json.dumps(variant.params, sort_keys=True),
        "split": photo.split,
    }


def main() -> None:
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    made = 0
    not_implemented: set[str] = set()

    for photo in load_photos():
        img = load(photo.photo_id)
        for name, attack in ATTACKS.items():
            try:
                variant = attack(img.copy(), random.Random(f"{SEED}:{photo.photo_id}:{name}"))
            except NotImplementedError:
                not_implemented.add(name)
                continue
            dst = VARIANTS_DIR / f"{photo.photo_id}__{name}.jpg"
            if not dst.exists():
                write(variant, dst)
                made += 1
            rows.append(manifest_row(photo, name, dst, variant))

    with MANIFEST.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{made} variants written, {len(rows)} in {MANIFEST}")
    if not_implemented:
        print("not implemented yet:", ", ".join(sorted(not_implemented)))


if __name__ == "__main__":
    main()
