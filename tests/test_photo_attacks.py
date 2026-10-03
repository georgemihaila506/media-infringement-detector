import hashlib
import json
import random

import cv2
import numpy as np
import pytest

from eval import photo_attacks as P
from eval.photos import Photo

SHAPES = {"landscape": (1200, 800), "portrait": (800, 1200), "panorama": (1600, 560)}
NAMES = list(P.ATTACKS)


def synthetic(w: int = 1200, h: int = 800) -> np.ndarray:
    """A gradient with a white disc: distinct everywhere, so crops and moves are detectable."""
    y, x = np.mgrid[0:h, 0:w]
    img = np.stack([x * 255 // w, y * 255 // h, (x + y) * 255 // (w + h)], axis=-1)
    img = img.astype(np.uint8)
    cv2.circle(img, (w // 3, h // 2), min(w, h) // 6, (255, 255, 255), -1)
    return img


@pytest.fixture(autouse=True)
def fillers(tmp_path, monkeypatch):
    """Collage fillers as plain-coloured JPEGs, so tests don't need the downloaded photos."""
    monkeypatch.setattr(P, "PHOTOS_DIR", tmp_path)
    names = []
    for i, colour in enumerate([(200, 40, 40), (40, 200, 40), (40, 40, 200), (200, 200, 40)]):
        name = f"filler_{i}"
        cv2.imwrite(str(tmp_path / f"{name}.jpg"), np.full((300, 400, 3), colour, np.uint8))
        names.append(name)
    monkeypatch.setattr(P, "COLLAGE_FILLERS", names)
    return names


def run(name: str, img: np.ndarray, seed: int = 0) -> P.PhotoVariant:
    return P.ATTACKS[name](img.copy(), random.Random(seed))


@pytest.mark.parametrize("name", NAMES)
def test_same_seed_gives_same_image_and_params(name):
    img = synthetic()
    a, b = run(name, img, 1), run(name, img, 1)
    assert a.params == b.params and a.quality == b.quality
    assert np.array_equal(a.image, b.image)


@pytest.mark.parametrize("name", NAMES)
def test_params_record_every_random_choice(name):
    """If two seeds produce the same params, they must produce the same image."""
    img, seen = synthetic(), {}
    for seed in range(15):
        v = run(name, img, seed)
        digest = hashlib.sha256(v.image.tobytes() + bytes([v.quality])).hexdigest()
        assert seen.setdefault(json.dumps(v.params, sort_keys=True), digest) == digest


@pytest.mark.parametrize("name", NAMES)
def test_attack_returns_a_valid_image(name):
    v = run(name, synthetic())
    assert v.image.dtype == np.uint8 and v.image.ndim == 3 and v.image.shape[2] == 3


@pytest.mark.parametrize("shape", SHAPES)
def test_resize_long_side_is_480_for_every_shape(shape):
    w, h = SHAPES[shape]
    out = run("resize_480", synthetic(w, h)).image
    assert max(out.shape[:2]) == 480
    assert out.shape[1] / out.shape[0] == pytest.approx(w / h, rel=0.01)


@pytest.mark.parametrize("fraction", [0.10, 0.20, 0.35])
@pytest.mark.parametrize("shape", SHAPES)
def test_crop_cuts_exactly_where_params_say(fraction, shape):
    w, h = SHAPES[shape]
    img = synthetic(w, h)
    keep = 1 - fraction
    for seed in range(10):
        v = P.crop(img.copy(), random.Random(seed), fraction)
        ch, cw = round(h * keep), round(w * keep)
        top = min(round(v.params["y"] * h), h - ch)
        left = min(round(v.params["x"] * w), w - cw)
        assert v.image.shape[:2] == (ch, cw)
        assert np.array_equal(v.image, img[top : top + ch, left : left + cw])


def test_pad_frame_and_square_modes():
    img = synthetic(600, 400)
    modes = {}
    for seed in range(40):
        modes.setdefault(run("pad", img, seed).params["mode"], seed)
    assert set(modes) == {"frame", "square"}

    frame = run("pad", img, modes["frame"])
    b, colour = frame.params["pixels"], P.PAD_COLOURS[frame.params["colour"]]
    assert frame.image.shape[:2] == (400 + 2 * b, 600 + 2 * b)
    assert (frame.image[:b] == colour).all() and (frame.image[:, -b:] == colour).all()
    assert np.array_equal(frame.image[b:-b, b:-b], img)

    square = run("pad", img, modes["square"])
    assert square.image.shape[:2] == (600, 600)
    assert np.array_equal(square.image[100:500], img)


def test_brightness_contrast_direction_follows_gamma():
    grey = np.full((50, 50, 3), 128, np.uint8)  # mid-grey: contrast leaves it alone
    for seed in range(30):
        v = run("brightness_contrast", grey, seed)
        mean = v.image.mean()
        assert mean > 130 if v.params["gamma"] > 1 else mean < 126
        assert 0.85 <= v.params["gamma"] <= 1.25
        assert abs(v.params["gamma"] - 1) >= 0.07 - 1e-9  # 1 - 0.93 isn't exactly 0.07
        assert 0.9 <= v.params["contrast"] <= 1.1


def test_paste_png_blends_by_alpha_and_opacity(tmp_path):
    png = tmp_path / "half.png"
    cv2.imwrite(str(png), np.full((10, 20, 4), (255, 255, 255, 128), np.uint8))
    img = np.zeros((100, 200, 3), np.uint8)

    out = P.paste_png(img, png, width=0.5, x=1, y=1)  # bottom-right corner
    assert out.shape == img.shape and img.max() == 0  # input untouched
    region = out[-50:, -100:]  # 0.5 of 200 wide, 10:20 aspect -> 100x50
    assert (region == 128).all()
    assert out[:-50].max() == 0 and out[:, :-100].max() == 0

    faded = P.paste_png(img, png, width=0.5, x=0, y=0, opacity=0.5)
    assert (faded[:50, :100] == 64).all()


def test_rotate_small_fills_the_frame():
    img = np.full((400, 600, 3), 200, np.uint8)
    cv2.circle(img, (300, 200), 80, (30, 30, 30), -1)
    for seed in range(10):
        v = run("rotate_small", img, seed)
        assert v.image.shape == img.shape
        assert 3 <= abs(v.params["angle"]) <= 15
        corners = [v.image[:3, :3], v.image[:3, -3:], v.image[-3:, :3], v.image[-3:, -3:]]
        assert min(c.mean() for c in corners) > 150  # no black corners


def test_rotate_90_swaps_width_and_height():
    img = synthetic(600, 400)
    for seed in range(4):
        assert run("rotate_90", img, seed).image.shape[:2] == (600, 400)


def test_collage_places_the_photo_in_the_recorded_tile():
    img = synthetic(600, 400)
    v = run("collage", img)
    tw, th, gap = 300, 200, max(2, round(0.01 * 600))
    r, c = divmod(v.params["tile"], 2)
    top, left = gap + r * (th + gap), gap + c * (tw + gap)
    assert np.array_equal(v.image[top : top + th, left : left + tw], P.fill(img, tw, th))
    assert len(v.params["fillers"]) == 3


def test_collage_never_uses_the_photo_as_its_own_filler(fillers):
    img = P.load(fillers[0])
    for seed in range(10):
        assert fillers[0] not in run("collage", img, seed).params["fillers"]


def test_write_rejects_images_that_are_not_bgr_uint8(tmp_path):
    with pytest.raises(ValueError, match="BGR uint8"):
        P.write(P.PhotoVariant(np.zeros((64, 64), np.uint8), {}), tmp_path / "x.jpg")
    with pytest.raises(ValueError, match="BGR uint8"):
        P.write(P.PhotoVariant(np.zeros((64, 64, 3), np.float32), {}), tmp_path / "x.jpg")


def test_manifest_rows_label_negatives_with_no_original(tmp_path):
    v = P.PhotoVariant(synthetic(), {"k": 1})
    dst = P.VARIANTS_DIR / "x__mirror.jpg"
    original = Photo("photo_1", 1, "original", "train", "", "a", "n")
    negative = Photo("photo_2", 2, "negative", "test", "", "a", "n")
    assert P.manifest_row(original, "mirror", dst, v)["original_id"] == "photo_1"
    row = P.manifest_row(negative, "mirror", dst, v)
    assert row["original_id"] == "" and row["split"] == "test"
    assert json.loads(row["params"]) == {"k": 1}
