"""Unit tests for the local asset manager."""

from __future__ import annotations

import io
from pathlib import Path
from PIL import Image
import pytest

from sketchforge.exceptions import AssetError
from sketchforge.rendering.asset_manager import AssetManager


def _make_sample_png_bytes(width: int = 10, height: int = 10, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_asset_manager_init(tmp_path: Path):
    mgr = AssetManager(tmp_path / "assets")
    assert mgr.directory.exists()

    with pytest.raises(ValueError, match="limits must be positive"):
        AssetManager(tmp_path / "assets2", max_file_bytes=0)


def test_asset_manager_import_bytes_and_retrieve(tmp_path: Path):
    mgr = AssetManager(tmp_path)
    data = _make_sample_png_bytes()

    asset = mgr.import_bytes(data, "test.png")
    assert len(asset.key) == 64
    assert asset.width == 10
    assert asset.height == 10
    assert asset.media_type == "image/png"
    assert asset.path.exists()

    # Reading bytes back
    retrieved = mgr.read_bytes(asset.key, ".png")
    assert retrieved == data

    # Data URI
    uri = mgr.data_uri(asset.key, ".png")
    assert uri.startswith("data:image/png;base64,")

    # List assets
    assets = mgr.list_assets()
    assert len(assets) == 1
    assert assets[0].key == asset.key

    # Delete asset
    mgr.delete(asset.key, ".png")
    assert not asset.path.exists()
    assert len(mgr.list_assets()) == 0


def test_asset_manager_validation(tmp_path: Path):
    mgr = AssetManager(tmp_path, max_file_bytes=500)
    data = _make_sample_png_bytes()

    # Invalid extension
    with pytest.raises(AssetError, match="unsupported asset type"):
        mgr.import_bytes(data, "test.exe")

    # Empty data
    with pytest.raises(AssetError, match="empty"):
        mgr.import_bytes(b"", "test.png")

    # Size limit exceeded
    with pytest.raises(AssetError, match="limit"):
        mgr.import_bytes(b"x" * 600, "test.png")

    # Mismatched extension/format
    with pytest.raises(AssetError, match="does not match"):
        mgr.import_bytes(data, "test.jpg")
