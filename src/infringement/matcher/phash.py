import numpy as np


def phash(gray: np.ndarray) -> int:
    """64-bit DCT perceptual hash of a grayscale image."""
    raise NotImplementedError


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
