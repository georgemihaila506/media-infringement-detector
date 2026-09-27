from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VideoFingerprint:
    t_ms: np.ndarray  # int32, sample timestamps
    hashes: np.ndarray  # uint64, one pHash per sample


@dataclass(frozen=True)
class VideoMatch:
    score: float
    offset_ms: int
    aligned_fraction: float
    mean_distance: float


def fingerprint_video(path: str, fps: float = 2.0) -> VideoFingerprint:
    """Sample frames, crop black bars with one box per video, hash each frame."""
    raise NotImplementedError


def compare_video(suspect: VideoFingerprint, original: VideoFingerprint) -> VideoMatch:
    """Offset voting over near-matching frame pairs."""
    raise NotImplementedError
