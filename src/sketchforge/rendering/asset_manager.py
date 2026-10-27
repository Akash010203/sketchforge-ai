"""Local, content-addressed storage for raster assets used by rendered designs.

Assets are stored as ``<sha256><extension>`` beneath a caller-selected directory.  The
content hash makes imports idempotent and gives documents a stable key without depending on
the original filename or its location.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from sketchforge.constants import SUPPORTED_IMAGE_EXTENSIONS
from sketchforge.exceptions import AssetError
from sketchforge.utilities.hashing import sha256_bytes
from sketchforge.utilities.paths import atomic_write_bytes, ensure_dir, safe_join

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_PIXELS = 60_000_000
_MIME_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".bmp": "image/bmp", ".webp": "image/webp", ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


@dataclass(frozen=True)
class Asset:
    """Metadata for a stored image asset."""

    key: str
    path: Path
    media_type: str
    width: int
    height: int
    size_bytes: int


class AssetManager:
    """Import and retrieve image assets inside a dedicated local asset directory.

    ``key`` values are lowercase SHA-256 digests.  Files are validated from their headers
    before they are decoded or persisted; small assets (including UI icons) are supported.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_pixels: int = DEFAULT_MAX_PIXELS,
    ) -> None:
        if max_file_bytes <= 0 or max_pixels <= 0:
            raise ValueError("asset limits must be positive")
        self.directory = ensure_dir(directory).resolve()
        self.max_file_bytes = max_file_bytes
        self.max_pixels = max_pixels

    def import_file(self, path: str | Path) -> Asset:
        """Validate and import a raster image from disk."""
        source = Path(path)
        if not source.is_file():
            raise AssetError(f"no such asset file: {source}")
        size = source.stat().st_size
        if size > self.max_file_bytes:
            raise AssetError(f"asset is {size} bytes; limit is {self.max_file_bytes} bytes")
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise AssetError(f"cannot read asset: {exc}") from exc
        return self.import_bytes(data, source.name)

    def import_bytes(self, data: bytes, filename: str) -> Asset:
        """Validate and store image bytes, returning stable metadata for the asset."""
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            raise AssetError(f"unsupported asset type {suffix or '(none)'}")
        if not data:
            raise AssetError("asset file is empty")
        if len(data) > self.max_file_bytes:
            raise AssetError(f"asset is {len(data)} bytes; limit is {self.max_file_bytes} bytes")
        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                image_format = (image.format or "").lower()
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AssetError(f"invalid image asset: {exc}") from exc
        expected_formats = {
            ".png": {"png"}, ".jpg": {"jpeg"}, ".jpeg": {"jpeg"},
            ".bmp": {"bmp"}, ".webp": {"webp"}, ".tif": {"tiff"},
            ".tiff": {"tiff"},
        }
        if image_format not in expected_formats[suffix]:
            raise AssetError(f"file extension {suffix!r} does not match image content")
        if width < 1 or height < 1 or width * height > self.max_pixels:
            raise AssetError(f"asset dimensions {width}x{height} exceed the pixel limit")

        key = sha256_bytes(data)
        target = safe_join(self.directory, f"{key}{suffix}")
        if not target.exists():
            atomic_write_bytes(target, data)
        return Asset(key, target, _MIME_TYPES[suffix], width, height, len(data))

    def resolve(self, key: str, extension: str) -> Path:
        """Resolve a digest and extension to an existing asset, rejecting unsafe paths."""
        if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
            raise AssetError("asset key must be a lowercase SHA-256 digest")
        suffix = extension.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            raise AssetError(f"unsupported asset type {suffix!r}")
        path = safe_join(self.directory, f"{key}{suffix}")
        if not path.is_file():
            raise AssetError(f"asset {key} was not found")
        return path

    def read_bytes(self, key: str, extension: str) -> bytes:
        """Read a previously imported asset."""
        try:
            return self.resolve(key, extension).read_bytes()
        except OSError as exc:
            raise AssetError(f"cannot read asset {key}: {exc}") from exc

    def data_uri(self, key: str, extension: str) -> str:
        """Return an inline ``data:`` URL suitable for self-contained HTML/SVG output."""
        suffix = extension.lower()
        payload = base64.b64encode(self.read_bytes(key, suffix)).decode("ascii")
        return f"data:{_MIME_TYPES[suffix]};base64,{payload}"

    def list_assets(self) -> list[Asset]:
        """List valid stored raster assets in stable key order."""
        assets: list[Asset] = []
        for path in sorted(self.directory.iterdir()):
            suffix = path.suffix.lower()
            key = path.stem
            if not path.is_file() or suffix not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
                continue
            try:
                with Image.open(path) as image:
                    width, height = image.size
                assets.append(Asset(key, path, _MIME_TYPES[suffix], width, height, path.stat().st_size))
            except (UnidentifiedImageError, OSError, ValueError):
                continue
        return assets

    def delete(self, key: str, extension: str) -> None:
        """Delete one stored asset; missing assets are reported as ``AssetError``."""
        path = self.resolve(key, extension)
        try:
            path.unlink()
        except OSError as exc:
            raise AssetError(f"cannot delete asset {key}: {exc}") from exc


__all__ = ["Asset", "AssetManager"]
