import numpy as np


def fingerprint_audio(path: str) -> np.ndarray:
    """Chromaprint raw fingerprint via `fpcalc -raw`, as uint32."""
    raise NotImplementedError


def compare_audio(suspect: np.ndarray, original: np.ndarray) -> tuple[float, int]:
    """Return (score, offset_ms) from bit-error offset voting."""
    raise NotImplementedError
