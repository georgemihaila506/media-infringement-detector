import shutil
import subprocess
from pathlib import Path

import pytest

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg and ffprobe",
)


def make_video(
    path: Path,
    seconds: float,
    *,
    size: str = "160x96",
    rate: int = 24,
    audio_tracks: int = 1,
    channels: int = 2,
) -> Path:
    """Write a small test-pattern video with a sine tone on each audio track."""
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        "-map", "0:v", *["-map", "1:a"] * audio_tracks,
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ac", str(channels),
        str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(autouse=True)
def assets_dir(tmp_path_factory, monkeypatch):
    """Keep generated overlay images out of eval/data during tests."""
    import eval.attacks

    path = tmp_path_factory.getbasetemp() / "assets"
    monkeypatch.setattr(eval.attacks, "ASSETS_DIR", path)
    return path
