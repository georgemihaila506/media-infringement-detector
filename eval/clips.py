"""Cut the catalog originals and negatives listed in eval/clips.csv.

Writes eval/data/clips/<clip_id>.mp4. Existing clips are skipped; delete eval/data/clips/
to rebuild from scratch.
"""

import csv
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

EVAL_DIR = Path(__file__).parent
CLIPS_CSV = EVAL_DIR / "clips.csv"
RAW_DIR = EVAL_DIR / "data" / "raw"
OUT_DIR = EVAL_DIR / "data" / "clips"

# How far a cut clip's duration may drift from the requested one, in seconds.
DURATION_TOLERANCE_S = 0.1


@dataclass(frozen=True)
class Clip:
    clip_id: str
    source: str
    start: str  # "HH:MM:SS", passed to ffmpeg as-is
    duration: int  # seconds
    role: str  # "original" | "negative"
    split: str  # "train" | "test"


def load_clips(path: Path = CLIPS_CSV) -> list[Clip]:
    with path.open(newline="") as f:
        return [Clip(**{**row, "duration": int(row["duration"])}) for row in csv.DictReader(f)]


def ffmpeg_cmd(clip: Clip, src: Path, dst: Path) -> list[str]:
    """Build the ffmpeg command that cuts one clip from src into dst.

    return the argument list, e.g. ["ffmpeg", "-ss", clip.start, ...]. Requirements:
    - exact cut: -ss and -t go before -i, and the video is re-encoded (no -c copy)
    - keep only the first video and the first audio stream (-map), audio downmixed to stereo
    - H.264 at CRF 18, AAC at 160k
    - MP4 index at the start of the file (-movflags +faststart)
    - never prompt for input (-y), and only log errors (-loglevel error)
    """
    return [
        "ffmpeg",
        "-ss",
        clip.start,
        "-t",
        str(clip.duration),
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-y",
        "-loglevel",
        "error",
        "-map_chapters",
        "-1",
        str(dst),
    ]


def probe(path: Path) -> dict:
    """Return ffprobe's JSON description of a file: {"format": {...}, "streams": [...]}."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def verify(clip: Clip, path: Path) -> None:
    """Raise ValueError if the cut file isn't what clips.csv asked for.

    using probe(path), check that:
    - format["duration"] (a string) is within DURATION_TOLERANCE_S of clip.duration
    - there is exactly one stream with codec_type "video" and one with "audio"
    - the audio stream has 2 channels
    """
    result = probe(path)
    duration = float(result["format"]["duration"])
    if abs(duration - clip.duration) > DURATION_TOLERANCE_S:
        raise ValueError(f"{clip.clip_id}: duration {duration} != {clip.duration}")
    if len(result["streams"]) != 2:
        raise ValueError(f"{clip.clip_id}: {len(result['streams'])} streams, expected 2")
    video_streams = [s for s in result["streams"] if s["codec_type"] == "video"]
    audio_streams = [s for s in result["streams"] if s["codec_type"] == "audio"]
    if len(video_streams) != 1:
        raise ValueError(f"{clip.clip_id}: {len(video_streams)} video streams, expected 1")
    if len(audio_streams) != 1:
        raise ValueError(f"{clip.clip_id}: {len(audio_streams)} audio streams, expected 1")
    channels = audio_streams[0].get("channels")
    if channels != 2:
        raise ValueError(f"{clip.clip_id}: audio has {channels} channels, expected 2")


def cut(clip: Clip) -> bool:
    """Cut one clip. Return False if it already existed."""
    dst = OUT_DIR / f"{clip.clip_id}.mp4"
    if dst.exists():
        return False
    # Write to a temporary name and rename only once verified, so an interrupted run
    # never leaves a half-written file that the next run would skip as done.
    tmp = dst.with_suffix(".tmp.mp4")
    subprocess.run(ffmpeg_cmd(clip, RAW_DIR / clip.source, tmp), check=True)
    verify(clip, tmp)
    tmp.rename(dst)
    return True


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clips = load_clips()
    for clip in clips:
        print(f"{'cut ' if cut(clip) else 'skip'} {clip.clip_id}")
    print(f"{len(clips)} clips in {OUT_DIR}")


if __name__ == "__main__":
    main()
