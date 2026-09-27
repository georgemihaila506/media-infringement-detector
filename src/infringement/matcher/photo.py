from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PhotoFingerprint:
    phash: int
    phash_mirrored: int
    keypoints: np.ndarray  # float32 (n, 2)
    descriptors: np.ndarray  # uint8 (n, 32), ORB


@dataclass(frozen=True)
class PhotoMatch:
    score: float
    inliers: int
    homography: np.ndarray | None


def fingerprint_photo(path: str) -> PhotoFingerprint:
    raise NotImplementedError


def compare_photo(suspect: PhotoFingerprint, original: PhotoFingerprint) -> PhotoMatch:
    """ORB matching with ratio test, then RANSAC homography."""
    raise NotImplementedError
