import subprocess
from pathlib import Path

import pytest

from eval import clips
from eval.clips import Clip, cut, ffmpeg_cmd, probe, verify
from tests.conftest import make_video, requires_ffmpeg

CLIP = Clip("c1", "film.mkv", "00:00:02", 5, "original", "train")


def value_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_ffmpeg_cmd_seeks_on_input_and_keeps_one_video_and_audio_stream():
    cmd = ffmpeg_cmd(CLIP, Path("in.mkv"), Path("out.mp4"))
    i = cmd.index("-i")
    assert cmd.index("-ss") < i and value_after(cmd, "-ss") == "00:00:02"
    assert cmd.index("-t") < i and value_after(cmd, "-t") == "5"
    maps = [cmd[k + 1] for k, arg in enumerate(cmd) if arg == "-map"]
    assert maps == ["0:v:0", "0:a:0"]
    assert value_after(cmd, "-map_chapters") == "-1"
    assert value_after(cmd, "-ac") == "2"
    assert "-y" in cmd
    assert cmd[-1] == "out.mp4"


def make_film(path: Path) -> Path:
    """A source like the Blender films: two audio tracks (5.1 and stereo) and chapters."""
    meta = path.with_suffix(".txt")
    meta.write_text(
        ";FFMETADATA1\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=5000\ntitle=one\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=5000\nEND=10000\ntitle=two\n"
    )
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=24:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
        "-i", str(meta),
        "-map", "0:v", "-map", "1:a", "-map", "1:a", "-map_chapters", "2",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-ac:a:0", "6", "-ac:a:1", "2",
        str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return path


@requires_ffmpeg
def test_cut_handles_surround_audio_extra_tracks_and_chapters(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw", tmp_path / "clips"
    raw.mkdir()
    out.mkdir()
    film = make_film(raw / "film.mkv")
    assert probe(film)["streams"][1]["channels"] == 6
    monkeypatch.setattr(clips, "RAW_DIR", raw)
    monkeypatch.setattr(clips, "OUT_DIR", out)

    assert cut(CLIP) is True
    info = probe(out / "c1.mp4")
    assert [s["codec_type"] for s in info["streams"]] == ["video", "audio"]
    assert info["streams"][1]["channels"] == 2
    assert float(info["format"]["duration"]) == pytest.approx(5, abs=0.1)

    assert cut(CLIP) is False  # already there: skipped
    assert not list(out.glob("*.tmp.*"))


@requires_ffmpeg
def test_verify_accepts_a_correct_clip(tmp_path):
    verify(CLIP, make_video(tmp_path / "ok.mp4", 5))


@requires_ffmpeg
@pytest.mark.parametrize(
    ("kwargs", "seconds", "error"),
    [
        ({}, 7, "duration"),
        ({"audio_tracks": 2}, 5, "streams"),
        ({"audio_tracks": 0}, 5, "streams"),
        ({"channels": 1}, 5, "channels"),
    ],
)
def test_verify_rejects_a_wrong_clip(tmp_path, kwargs, seconds, error):
    path = make_video(tmp_path / "bad.mp4", seconds, **kwargs)
    with pytest.raises(ValueError, match=error):
        verify(CLIP, path)
