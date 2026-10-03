import hashlib
import json
import random
import subprocess

import cv2
import pytest

from eval import attacks
from eval.clips import Clip, probe
from tests.conftest import make_video, requires_ffmpeg

SECONDS = 40  # as long as typical real clips, so fixed-length bugs (e.g. 30 s of noise) show
WIDTH, HEIGHT = 160, 96
CLIP = Clip("c1", "unused.mp4", "00:00:00", SECONDS, "original", "train")
NAMES = list(attacks.ATTACKS)


def build(name: str, seed: int = 0) -> attacks.Variant:
    return attacks.ATTACKS[name](CLIP, random.Random(seed))


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("video") / "clip.mp4", SECONDS)


def render(source, variant, dst):
    subprocess.run(attacks.ffmpeg_cmd(source, variant, dst), check=True)
    return probe(dst)


def video_stream(info):
    return next(s for s in info["streams"] if s["codec_type"] == "video")


@pytest.mark.parametrize("name", NAMES)
def test_same_seed_gives_same_variant(name):
    assert build(name, 1) == build(name, 1)


@pytest.mark.parametrize("name", NAMES)
def test_params_record_every_random_choice(name):
    """If two seeds produce the same params, they must produce the same ffmpeg arguments."""
    seen = {}
    for seed in range(25):
        v = build(name, seed)
        args = (v.input_args, v.extra_inputs, v.output_args)
        assert seen.setdefault(json.dumps(v.params, sort_keys=True), args) == args


@requires_ffmpeg
@pytest.mark.parametrize("name", NAMES)
def test_attack_output_has_expected_streams_and_length(name, source, tmp_path):
    v = build(name)
    info = render(source, v, tmp_path / "out.mp4")
    kinds = sorted(s["codec_type"] for s in info["streams"])
    assert kinds == (["video"] if name == "strip_audio" else ["audio", "video"])
    if name.startswith("subclip"):
        expected = v.params["seconds"]
    elif name.startswith("speed"):
        expected = SECONDS / v.params["factor"]
    else:
        expected = SECONDS
    assert float(info["format"]["duration"]) == pytest.approx(expected, abs=0.15)


@requires_ffmpeg
def test_resize_is_360_high_with_even_width(source, tmp_path):
    out = video_stream(render(source, build("resize_360p"), tmp_path / "out.mp4"))
    assert out["height"] == 360 and out["width"] % 2 == 0
    assert out["width"] / out["height"] == pytest.approx(WIDTH / HEIGHT, abs=0.01)


@requires_ffmpeg
def test_letterbox_pads_to_4_3_without_rescaling(source, tmp_path):
    out = video_stream(render(source, build("letterbox"), tmp_path / "out.mp4"))
    assert (out["width"], out["height"]) == (WIDTH, WIDTH * 3 // 4)


@pytest.mark.parametrize("fraction", [0.10, 0.20, 0.35])
def test_crop_window_stays_inside_the_frame(fraction):
    for seed in range(50):
        p = attacks.crop(CLIP, random.Random(seed), fraction).params
        assert 0 <= p["x"] <= fraction and 0 <= p["y"] <= fraction
        assert p["x"] + (1 - fraction) <= 1 + 1e-9 and p["y"] + (1 - fraction) <= 1 + 1e-9


@requires_ffmpeg
@pytest.mark.parametrize("name", ["crop_10", "crop_20", "crop_35"])
def test_crop_keeps_the_right_share(name, source, tmp_path):
    keep = 1 - build(name).params["fraction"]
    out = video_stream(render(source, build(name), tmp_path / "out.mp4"))
    assert out["width"] == pytest.approx(WIDTH * keep, abs=2)
    assert out["height"] == pytest.approx(HEIGHT * keep, abs=2)


@requires_ffmpeg
def test_picture_in_picture_keeps_size_and_frame_rate(source, tmp_path):
    out = video_stream(render(source, build("pip"), tmp_path / "out.mp4"))
    assert (out["width"], out["height"], out["avg_frame_rate"]) == (WIDTH, HEIGHT, "24/1")


@requires_ffmpeg
def test_replace_audio_is_reproducible(source, tmp_path):
    def audio_digest(dst):
        render(source, build("replace_audio"), dst)
        pcm = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(dst), "-map", "0:a", "-f", "s16le", "-"],
            check=True,
            capture_output=True,
        ).stdout
        return hashlib.sha256(pcm).hexdigest()

    assert audio_digest(tmp_path / "a.mp4") == audio_digest(tmp_path / "b.mp4")


def test_text_png_is_opaque_text_on_transparent_background(assets_dir):
    path = attacks.text_png("FilmDrop 24/7")  # the "/" must not become a directory
    assert path.parent == assets_dir
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    assert img.shape[2] == 4
    assert img[0, 0, 3] == 0 and img[-1, -1, 3] == 0
    assert img[..., 3].max() == 255


@pytest.mark.parametrize("style", attacks.LOGO_STYLES)
def test_logo_png_is_white_on_transparent(style):
    img = cv2.imread(str(attacks.logo_png(style)), cv2.IMREAD_UNCHANGED)
    assert img.shape == (400, 400, 4)
    assert img[0, 0, 3] == 0
    assert img[..., 3].max() == 255


def test_badge_letters_are_cut_out():
    img = cv2.imread(str(attacks.logo_png("badge")), cv2.IMREAD_UNCHANGED)
    box = img[100:300, 20:380, 3]
    assert box[5, 5] == 255  # the box itself is opaque
    assert (box == 0).sum() > 1000  # the letters are fully transparent


@requires_ffmpeg
@pytest.mark.parametrize("name", ["text_overlay", "logo_overlay"])
def test_overlays_keep_the_frame_size(name, source, tmp_path):
    out = video_stream(render(source, build(name), tmp_path / "out.mp4"))
    assert (out["width"], out["height"]) == (WIDTH, HEIGHT)
