"""Download the catalog photos and negatives listed in eval/photos.csv.

Photos come from Lorem Picsum (picsum.photos), which serves Unsplash photos by a fixed id
under the Unsplash licence. Each is saved as eval/data/photos/<photo_id>.jpg, scaled so its
long side is LONG_SIDE pixels with the original aspect ratio. Existing photos are skipped;
delete eval/data/photos/ to download everything again.
"""

import csv
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

EVAL_DIR = Path(__file__).parent
PHOTOS_CSV = EVAL_DIR / "photos.csv"
OUT_DIR = EVAL_DIR / "data" / "photos"

LONG_SIDE = 1600
PICSUM = "https://picsum.photos"


@dataclass(frozen=True)
class Photo:
    photo_id: str
    picsum_id: int
    role: str  # "original" | "negative"
    split: str  # "train" | "test"
    group: str  # near-duplicate group shared by an original and its hard negatives; may be ""
    author: str
    note: str


def load_photos(path: Path = PHOTOS_CSV) -> list[Photo]:
    with path.open(newline="") as f:
        return [Photo(**{**row, "picsum_id": int(row["picsum_id"])}) for row in csv.DictReader(f)]


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def download(photo: Photo) -> bool:
    """Download one photo. Return False if it already existed."""
    dst = OUT_DIR / f"{photo.photo_id}.jpg"
    if dst.exists():
        return False
    info = json.loads(fetch(f"{PICSUM}/id/{photo.picsum_id}/info"))
    # Picsum crops to whatever size is requested, so ask for the original aspect ratio.
    scale = LONG_SIDE / max(info["width"], info["height"])
    w, h = round(info["width"] * scale), round(info["height"] * scale)
    data = fetch(f"{PICSUM}/id/{photo.picsum_id}/{w}/{h}")

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"{photo.photo_id}: download is not a decodable image")
    if (img.shape[1], img.shape[0]) != (w, h):
        raise ValueError(f"{photo.photo_id}: got {img.shape[1]}x{img.shape[0]}, wanted {w}x{h}")

    tmp = dst.with_suffix(".tmp.jpg")
    tmp.write_bytes(data)
    tmp.rename(dst)
    return True


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    photos = load_photos()
    for photo in photos:
        print(f"{'got ' if download(photo) else 'skip'} {photo.photo_id}")
    print(f"{len(photos)} photos in {OUT_DIR}")


if __name__ == "__main__":
    main()
