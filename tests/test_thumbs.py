"""Tests for filemanaty.thumbs."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from filemanaty.thumbs import generate_thumbnail, ThumbError, cache_key, cache_path


def _make_png(path: Path, size=(500, 300), color=(255, 0, 0)):
    img = Image.new("RGB", size, color)
    img.save(path, format="PNG")


def test_generate_thumbnail_returns_webp_bytes(tmp_path):
    src = tmp_path / "big.png"
    _make_png(src, size=(800, 600))

    data = generate_thumbnail(src, max_dimension=320)
    # WebP magic bytes: "RIFF" header + "WEBP" tag.
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WEBP"
    out = Image.open(io.BytesIO(data))
    assert out.format == "WEBP"
    assert max(out.size) == 320
    # Aspect preserved: 800/600 = 4/3 -> at max 320 -> (320, 240)
    assert out.size == (320, 240)


def test_generate_thumbnail_corrupt_raises(tmp_path):
    src = tmp_path / "broken.png"
    src.write_bytes(b"this is not a png")
    with pytest.raises(ThumbError):
        generate_thumbnail(src, max_dimension=320)


def test_generate_thumbnail_unsupported_extension_raises(tmp_path):
    src = tmp_path / "file.exe"
    src.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00")
    with pytest.raises(ThumbError):
        generate_thumbnail(src, max_dimension=320)


def test_cache_key_stable():
    a = cache_key("outputs", "img.png", 12345, 320)
    b = cache_key("outputs", "img.png", 12345, 320)
    assert a == b


def test_cache_key_changes_with_mtime():
    a = cache_key("outputs", "img.png", 12345, 320)
    b = cache_key("outputs", "img.png", 99999, 320)
    assert a != b


def test_cache_key_changes_with_max_dimension():
    a = cache_key("outputs", "img.png", 12345, 320)
    b = cache_key("outputs", "img.png", 12345, 256)
    assert a != b


def test_cache_key_changes_with_root_id():
    a = cache_key("outputs", "img.png", 12345, 320)
    b = cache_key("inputs", "img.png", 12345, 320)
    assert a != b


def test_cache_path_uses_webp_extension(tmp_path):
    p = cache_path(tmp_path, "abc123")
    assert p == tmp_path / "abc123.webp"


def test_cache_key_canonicalizes_dot_segments():
    a = cache_key("r", "sub/./img.png", 123, 320)
    b = cache_key("r", "sub/img.png", 123, 320)
    assert a == b
