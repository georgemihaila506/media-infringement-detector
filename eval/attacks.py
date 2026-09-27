"""Generate attacked variants of every clip, and the manifest the evaluation reads.

Every attack in ATTACKS is applied to every clip in eval/clips.csv, originals and negatives
alike, producing eval/data/variants/<clip_id>__<attack>.mp4. Existing variants are skipped,
but each still gets a manifest row: attacks are deterministic, so the row is the same whether
the file was written now or on an earlier run.

Manifest (eval/data/manifest.csv): variant_path, clip_id, original_id, attack, params, split.
original_id is the clip_id for variants of an original, and empty for variants of a negative,
which a correct system matches to nothing.
"""

import csv
import json
import random
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from eval.clips import EVAL_DIR, Clip, load_clips, probe
from eval.clips import OUT_DIR as CLIPS_DIR

SEED = 1
DATA_DIR = EVAL_DIR / "data"
VARIANTS_DIR = DATA_DIR / "variants"
ASSETS_DIR = DATA_DIR / "assets"  # generated overlay images
MANIFEST = DATA_DIR / "manifest.csv"

# Invented re-uploader channel names for text_overlay; deliberately not real brands.
CAPTIONS = ["ReelClips HD", "MovieVault", "clipzone.tv", "FilmDrop 24/7", "BestScenes"]
# Invented watermark shapes for logo_overlay, drawn by logo_png.
LOGO_STYLES = ["play", "badge", "diamond"]

# Encoding for every variant. Attack output_args come after these, and ffmpeg uses the last
# value given for an option, so an attack can override any of them.
# fmt: off
ENCODE_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
    "-c:a", "aac", "-b:a", "128k",
    "-movflags", "+faststart",
]
# fmt: on


@dataclass(frozen=True)
class Variant:
    params: dict[str, object]  # recorded in the manifest; include every random choice
    input_args: list[str] = field(default_factory=list)  # before -i <clip>, e.g. -ss/-t
    extra_inputs: list[str] = field(default_factory=list)  # e.g. ["-i", "logo.png"]
    output_args: list[str] = field(default_factory=list)  # filters, -map, overrides


# An attack gets the clip and a random generator seeded for this (clip, attack) pair only,
# so adding, removing or reordering attacks never changes the others' output.
Attack = Callable[[Clip, random.Random], Variant]


# --- Examples ---------------------------------------------------------------------------


def recompress(clip: Clip, rng: random.Random) -> Variant:
    """Heavy re-encode with visible blocking: the cheapest evasion there is."""
    return Variant({"crf": 35}, output_args=["-crf", "35"])


def mirror(clip: Clip, rng: random.Random) -> Variant:
    """Flip left to right. Defeats a plain pHash; the suspect side hashes mirrored too."""
    return Variant({}, output_args=["-vf", "hflip"])


def subclip(clip: Clip, rng: random.Random, seconds: int) -> Variant:
    """A short excerpt from a random point in the clip."""
    start = round(rng.uniform(0, clip.duration - seconds), 2)
    return Variant(
        {"start": start, "seconds": seconds},
        input_args=["-ss", str(start), "-t", str(seconds)],
    )


# --- Attacks ----------------------------------------------------------------------------


def resize(clip: Clip, rng: random.Random) -> Variant:
    """Downscale to 360 pixels high, keeping the aspect ratio (-2 keeps the width even)."""
    return Variant({"height": 360}, output_args=["-vf", "scale=-2:360"])


def letterbox(clip: Clip, rng: random.Random) -> Variant:
    """Pad the picture to 4:3 with black bars, as when re-uploaded in a player.

    Only adds bars, never rescales, so this tests the bars alone. Wide pictures get bars
    above and below, tall ones at the sides; ceil(.../2)*2 keeps dimensions even.
    """
    pad = (
        "pad=w='max(iw,ceil(ih*4/3/2)*2)':h='max(ih,ceil(iw*3/4/2)*2)':x='(ow-iw)/2':y='(oh-ih)/2'"
    )
    return Variant({"frame": "4:3"}, output_args=["-vf", pad])


def crop(clip: Clip, rng: random.Random, fraction: float) -> Variant:
    """Cut away `fraction` of the width and height, at a random position.

    x and y are the left and top edges as shares of the frame; keeping them at most
    `fraction` keeps the window inside the picture.
    """
    keep = round(1 - fraction, 3)
    x = round(rng.uniform(0, fraction), 3)
    y = round(rng.uniform(0, fraction), 3)
    params = {"fraction": fraction, "x": x, "y": y}
    return Variant(params, output_args=["-vf", f"crop=iw*{keep}:ih*{keep}:iw*{x}:ih*{y}"])


def brightness_contrast(clip: Clip, rng: random.Random) -> Variant:
    """Lighten or darken with gamma, plus a mild contrast change.

    Gamma rather than brightness: brightness shifts every pixel equally and crushes dark
    scenes to black, while gamma keeps black and white in place. Each variant changes the
    picture visibly (gamma at least 0.07 from 1) yet stays watchable on the darkest clips.
    """
    if rng.random() < 0.5:
        gamma = round(rng.uniform(0.85, 0.93), 2)  # darker
    else:
        gamma = round(rng.uniform(1.08, 1.25), 2)  # lighter
    contrast = round(rng.uniform(0.9, 1.1), 2)
    return Variant(
        {"gamma": gamma, "contrast": contrast},
        output_args=["-vf", f"eq=gamma={gamma}:contrast={contrast}"],
    )


def text_png(text: str) -> Path:
    """Render white, black-outlined text on a transparent background, once per caption.

    Drawn large; overlay_variant scales it to each video. This ffmpeg build has no drawtext
    filter, hence the detour through an image.
    """
    slug = "".join(c if c.isalnum() else "_" for c in text.lower())
    path = ASSETS_DIR / f"text_{slug}.png"
    if path.exists():
        return path
    font, scale, thickness, outline = cv2.FONT_HERSHEY_DUPLEX, 3, 6, 12
    (w, h), baseline = cv2.getTextSize(text, font, scale, outline)
    pad = outline
    img = np.zeros((h + baseline + 2 * pad, w + 2 * pad, 4), np.uint8)  # BGRA, transparent
    origin = (pad, pad + h)
    cv2.putText(img, text, origin, font, scale, (0, 0, 0, 255), outline, cv2.LINE_AA)
    cv2.putText(img, text, origin, font, scale, (255, 255, 255, 255), thickness, cv2.LINE_AA)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def overlay_variant(
    png: Path, width: float, x: str, y: str, params: dict, opacity: float = 1.0
) -> Variant:
    """Overlay a PNG scaled to `width` times the video's width, at ffmpeg expressions x, y.

    In x and y, W/H are the video's size and w/h the scaled image's. opacity below 1 makes
    the image see-through. The single image frame stays on screen for the whole clip, and
    the clip's audio is kept automatically.
    """
    fade = f",format=rgba,colorchannelmixer=aa={opacity}" if opacity < 1 else ""
    graph = f"[1:v][0:v]scale=w=rw*{width}:h=-1{fade}[img];[0:v][img]overlay=x={x}:y={y}"
    return Variant(params, extra_inputs=["-i", str(png)], output_args=["-filter_complex", graph])


def text_overlay(clip: Clip, rng: random.Random) -> Variant:
    """Burn a caption into the picture, like a re-uploader's channel name."""
    text = rng.choice(CAPTIONS)
    width = round(rng.uniform(0.2, 0.35), 3)
    left = round(rng.uniform(0.03, 0.97 - width), 3)
    margin = round(rng.uniform(0.03, 0.1), 3)
    edge = rng.choice(["top", "bottom"])
    y = f"H*{margin}" if edge == "top" else f"H*(1-{margin})-h"
    params = {"text": text, "width": width, "left": left, "edge": edge, "margin": margin}
    return overlay_variant(text_png(text), width, f"W*{left}", y, params)


def logo_png(style: str) -> Path:
    """Draw an invented white logo on a transparent 400x400 canvas, once per style.

    Opacity is applied later by overlay_variant, so one image serves every variant.
    """
    path = ASSETS_DIR / f"logo_{style}.png"
    if path.exists():
        return path
    white, aa = (255, 255, 255, 255), cv2.LINE_AA
    img = np.zeros((400, 400, 4), np.uint8)  # BGRA, transparent
    if style == "play":  # ring with a play triangle
        cv2.circle(img, (200, 200), 170, white, 28, aa)
        triangle = np.array([[160, 110], [160, 290], [300, 200]], np.int32)
        cv2.fillPoly(img, [triangle], white, aa)
    elif style == "badge":  # solid box with the letters cut out
        cv2.rectangle(img, (20, 100), (380, 300), white, -1)
        # putText doesn't reliably write alpha, so draw the letters into a mask and
        # subtract it from the alpha channel; the mask's soft edges keep them smooth.
        letters = np.zeros(img.shape[:2], np.uint8)
        cv2.putText(letters, "TV", (95, 262), cv2.FONT_HERSHEY_DUPLEX, 5, 255, 18, aa)
        img[..., 3] = np.minimum(img[..., 3], 255 - letters)
    elif style == "diamond":  # diamond outline with a solid centre
        outer = np.array([[200, 20], [380, 200], [200, 380], [20, 200]], np.int32)
        inner = np.array([[200, 110], [290, 200], [200, 290], [110, 200]], np.int32)
        cv2.polylines(img, [outer], True, white, 26, aa)
        cv2.fillPoly(img, [inner], white, aa)
    else:
        raise ValueError(f"unknown logo style {style!r}")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def logo_overlay(clip: Clip, rng: random.Random) -> Variant:
    """A semi-transparent logo in a corner, like a TV channel's watermark."""
    style = rng.choice(LOGO_STYLES)
    corner = rng.choice(["top_left", "top_right", "bottom_left", "bottom_right"])
    width = round(rng.uniform(0.08, 0.15), 3)
    margin = round(rng.uniform(0.02, 0.05), 3)
    opacity = round(rng.uniform(0.4, 0.7), 2)
    x = f"W*{margin}" if corner.endswith("left") else f"W*(1-{margin})-w"
    y = f"H*{margin}" if corner.startswith("top") else f"H*(1-{margin})-h"
    params = {
        "style": style,
        "corner": corner,
        "width": width,
        "margin": margin,
        "opacity": opacity,
    }
    return overlay_variant(logo_png(style), width, x, y, params, opacity)


def speed(clip: Clip, rng: random.Random, factor: float) -> Variant:
    """Play at `factor` times normal speed. Offset voting can't handle this (measured only).

    Faster playback means smaller timestamps, so setpts (video) uses 1/factor while
    atempo (audio) uses factor.
    """
    graph = f"[0:v]setpts={round(1 / factor, 4)}*PTS[v];[0:a]atempo={factor}[a]"
    return Variant(
        {"factor": factor},
        output_args=["-filter_complex", graph, "-map", "[v]", "-map", "[a]"],
    )


def picture_in_picture(clip: Clip, rng: random.Random) -> Variant:
    """The clip shrunk into a window over a plain background (measured only).

    The background is the clip itself painted over with a solid box, so it has exactly the
    clip's size, frame rate and length, with no generated source to cut short.
    """
    size = round(rng.uniform(0.4, 0.6), 3)
    left = round(rng.uniform(0, 1 - size), 3)
    top = round(rng.uniform(0, 1 - size), 3)
    color = rng.choice(["black", "gray", "navy", "darkgreen"])
    graph = (
        f"[0:v]split[a][b];"
        f"[a]drawbox=x=0:y=0:w=iw:h=ih:color={color}:t=fill[bg];"
        f"[b]scale=w=iw*{size}:h=-2[fg];"
        f"[bg][fg]overlay=x=W*{left}:y=H*{top}[v]"
    )
    params = {"size": size, "left": left, "top": top, "background": color}
    return Variant(params, output_args=["-filter_complex", graph, "-map", "[v]", "-map", "0:a"])


def strip_audio(clip: Clip, rng: random.Random) -> Variant:
    """Remove the audio track, so only the picture can match."""
    return Variant({}, output_args=["-an"])


def replace_audio(clip: Clip, rng: random.Random) -> Variant:
    """Keep the picture, swap in unrelated audio (as re-uploaders do to dodge audio matching).

    The noise source never ends; -shortest stops the output with the video. Its seed comes
    from rng, since anoisesrc otherwise picks a new random seed on every run.
    """
    colour = rng.choice(["pink", "brown"])
    amplitude = round(rng.uniform(0.05, 0.2), 2)
    seed = rng.randrange(2**32)
    noise = f"anoisesrc=colour={colour}:amplitude={amplitude}:seed={seed}"
    return Variant(
        {"noise": colour, "amplitude": amplitude, "seed": seed},
        extra_inputs=["-f", "lavfi", "-i", noise],
        output_args=["-map", "0:v", "-map", "1:a", "-shortest"],
    )


# fmt: off
ATTACKS: dict[str, Attack] = {
    "recompress":          recompress,
    "resize_360p":         resize,
    "letterbox":           letterbox,
    "mirror":              mirror,
    "crop_10":             lambda c, r: crop(c, r, 0.10),
    "crop_20":             lambda c, r: crop(c, r, 0.20),
    "crop_35":             lambda c, r: crop(c, r, 0.35),
    "brightness_contrast": brightness_contrast,
    "text_overlay":        text_overlay,
    "logo_overlay":        logo_overlay,
    "speed_095":           lambda c, r: speed(c, r, 0.95),
    "speed_105":           lambda c, r: speed(c, r, 1.05),
    "subclip_5":           lambda c, r: subclip(c, r, 5),
    "subclip_15":          lambda c, r: subclip(c, r, 15),
    "pip":                 picture_in_picture,
    "strip_audio":         strip_audio,
    "replace_audio":       replace_audio,
}
# fmt: on


# --- Plumbing ---------------------------------------------------------------------------


def ffmpeg_cmd(src: Path, variant: Variant, dst: Path) -> list[str]:
    return [
        "ffmpeg", "-loglevel", "error", "-y",
        *variant.input_args, "-i", str(src),
        *variant.extra_inputs,
        *ENCODE_ARGS, *variant.output_args,
        str(dst),
    ]  # fmt: skip


def check(path: Path) -> None:
    """Raise ValueError if the variant has no video or is implausibly short."""
    info = probe(path)
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError(f"{path.name}: no video stream")
    if float(info["format"]["duration"]) < 1:
        raise ValueError(f"{path.name}: shorter than 1 s")


def main() -> None:
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    made = 0
    not_implemented: set[str] = set()

    for clip in load_clips():
        src = CLIPS_DIR / f"{clip.clip_id}.mp4"
        for name, attack in ATTACKS.items():
            try:
                variant = attack(clip, random.Random(f"{SEED}:{clip.clip_id}:{name}"))
            except NotImplementedError:
                not_implemented.add(name)
                continue

            dst = VARIANTS_DIR / f"{clip.clip_id}__{name}.mp4"
            if not dst.exists():
                tmp = dst.with_suffix(".tmp.mp4")
                subprocess.run(ffmpeg_cmd(src, variant, tmp), check=True)
                check(tmp)
                tmp.rename(dst)
                made += 1

            rows.append(
                {
                    "variant_path": str(dst.relative_to(DATA_DIR)),
                    "clip_id": clip.clip_id,
                    "original_id": clip.clip_id if clip.role == "original" else "",
                    "attack": name,
                    "params": json.dumps(variant.params, sort_keys=True),
                    "split": clip.split,
                }
            )
        print(f"{clip.clip_id}: done")

    with MANIFEST.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{made} variants written, {len(rows)} in {MANIFEST}")
    if not_implemented:
        print("not implemented yet:", ", ".join(sorted(not_implemented)))


if __name__ == "__main__":
    main()
