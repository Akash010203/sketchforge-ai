"""Safe image loading.

Validates before decoding (extension, file size, magic bytes, header dimensions) so a hostile or
corrupt file is rejected cheaply, then decodes with OpenCV and normalizes the pixel format to
8-bit BGR. The decoded original is kept untouched; later stages work on copies.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from sketchforge.bootstrap import VisionConfig
from sketchforge.constants import SUPPORTED_IMAGE_EXTENSIONS
from sketchforge.exceptions import ImageLoadError
from sketchforge.utilities.hashing import sha256_bytes

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)


@dataclass(frozen=True)
class LoadedImage:
    """An imported sketch. ``bgr`` is the untouched original pixels (treat as read-only)."""

    name: str
    path: Path | None
    sha256: str
    bgr: np.ndarray
    file_bytes: int

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])


def _sniff_format(data: bytes) -> str | None:
    for magic, name in _MAGIC:
        if data.startswith(magic):
            return name
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _to_bgr8(decoded: np.ndarray) -> np.ndarray:
    if decoded.dtype == np.uint16:
        decoded = (decoded / 257.0).astype(np.uint8)
    elif decoded.dtype != np.uint8:
        decoded = np.clip(decoded, 0, 255).astype(np.uint8)
    if decoded.ndim == 2:
        return cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGR)
    if decoded.shape[2] == 4:
        alpha = decoded[..., 3:4].astype(np.float32) / 255.0
        rgb = decoded[..., :3].astype(np.float32)
        return np.clip(rgb * alpha + 255.0 * (1.0 - alpha), 0, 255).astype(np.uint8)
    return decoded[..., :3].copy()


def load_image_bytes(data: bytes, name: str, limits: VisionConfig | None = None) -> LoadedImage:
    limits = limits or VisionConfig()
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ImageLoadError(
            f"unsupported file type {suffix or '(none)'}; use one of "
            f"{', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}"
        )
    if len(data) == 0:
        raise ImageLoadError("file is empty")
    if len(data) > limits.max_file_bytes:
        raise ImageLoadError(
            f"file is {len(data) / 1e6:.1f} MB; the limit is {limits.max_file_bytes / 1e6:.0f} MB"
        )
    if _sniff_format(data) is None:
        raise ImageLoadError("file content is not a recognised image format")

    # Header-only dimension check *before* decoding (decompression-bomb guard).
    try:
        with Image.open(io.BytesIO(data)) as header:
            hw, hh = header.size
            has_alpha = header.mode in ("RGBA", "LA", "PA") or "transparency" in header.info
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageLoadError(f"cannot read image header: {exc}") from exc
    if min(hw, hh) < limits.min_side_px or max(hw, hh) > limits.max_side_px:
        raise ImageLoadError(
            f"image is {hw}x{hh}; sides must be between {limits.min_side_px} and "
            f"{limits.max_side_px} px"
        )
    if hw * hh > limits.max_pixels:
        raise ImageLoadError(f"image has {hw * hh / 1e6:.0f} MP; the limit is "
                             f"{limits.max_pixels / 1e6:.0f} MP")

    buf = np.frombuffer(data, dtype=np.uint8)
    flag = cv2.IMREAD_UNCHANGED if has_alpha else cv2.IMREAD_COLOR  # COLOR applies EXIF rotation
    decoded = cv2.imdecode(buf, flag)
    if decoded is None:
        raise ImageLoadError("image data is corrupt or could not be decoded")
    bgr = _to_bgr8(decoded)
    if min(bgr.shape[:2]) < limits.min_side_px:
        raise ImageLoadError("decoded image is too small")
    bgr.setflags(write=False)
    return LoadedImage(
        name=Path(name).name, path=None, sha256=sha256_bytes(data), bgr=bgr, file_bytes=len(data)
    )


def load_image(path: str | Path, limits: VisionConfig | None = None) -> LoadedImage:
    p = Path(path)
    if not p.is_file():
        raise ImageLoadError(f"no such file: {p}")
    limits = limits or VisionConfig()
    size = p.stat().st_size
    if size > limits.max_file_bytes:  # do not even read oversized files
        raise ImageLoadError(
            f"file is {size / 1e6:.1f} MB; the limit is {limits.max_file_bytes / 1e6:.0f} MB"
        )
    loaded = load_image_bytes(p.read_bytes(), p.name, limits)
    return LoadedImage(
        name=loaded.name, path=p.resolve(), sha256=loaded.sha256, bgr=loaded.bgr,
        file_bytes=loaded.file_bytes,
    )


def from_array(bgr: np.ndarray, name: str = "array.png") -> LoadedImage:
    """Wrap an in-memory BGR image (used by tests and the synthetic generator)."""
    if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.dtype != np.uint8:
        raise ImageLoadError("expected an 8-bit BGR image array")
    data = np.ascontiguousarray(bgr)
    data.setflags(write=False)
    return LoadedImage(
        name=name, path=None, sha256=sha256_bytes(data.tobytes()), bgr=data, file_bytes=data.nbytes
    )
