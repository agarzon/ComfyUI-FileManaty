"""Tests for filemanaty.thumbs."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

from filemanaty.thumbs import (
    generate_thumbnail, ThumbError, cache_path, invalidate, prune, tmp_cache_path,
)


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


# --- video thumbnails -------------------------------------------------------
# PyAV is a ComfyUI-core dep, not a test dep, so `av` is faked here exactly as
# tests/test_metadata.py does. What's worth checking is ours, not FFmpeg's: the
# seek lands mid-clip, and an unseekable container still yields a thumbnail.

class _FakeFrame:
    def __init__(self, color):
        self._img = Image.new("RGB", (640, 480), color)

    def to_image(self):
        return self._img


class _FakeStream:
    thread_type = None


class _FakeVideoContainer:
    def __init__(self, duration, seek_error=None):
        self.duration = duration
        self.streams = type("S", (), {"video": [_FakeStream()]})()
        self.seeks = []
        self._seek_error = seek_error

    def seek(self, offset):
        if self._seek_error is not None:
            raise self._seek_error
        self.seeks.append(offset)

    def decode(self, _stream):
        # Black before a seek, red after — mirrors a clip that fades in.
        yield _FakeFrame((200, 0, 0) if self.seeks else (0, 0, 0))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeAv:
    def __init__(self, container):
        self.container = container

    def open(self, _path):
        return self.container


def _install_fake_av(monkeypatch, container):
    monkeypatch.setitem(sys.modules, "av", _FakeAv(container))
    return container


def test_generate_thumbnail_video_seeks_to_midpoint(monkeypatch, tmp_path):
    container = _install_fake_av(monkeypatch, _FakeVideoContainer(duration=10_000_000))

    data = generate_thumbnail(tmp_path / "clip.mp4", max_dimension=320, video=True)

    assert container.seeks == [5_000_000]  # AV_TIME_BASE units, half of duration
    assert data[8:12] == b"WEBP"
    out = Image.open(io.BytesIO(data))
    assert out.size == (320, 240)
    assert out.convert("RGB").getpixel((0, 0))[0] > 100  # post-seek frame, not frame 0


def test_generate_thumbnail_video_unseekable_falls_back_to_first_frame(
        monkeypatch, tmp_path):
    # An unseekable container must still produce a thumbnail, not an error page.
    _install_fake_av(monkeypatch, _FakeVideoContainer(
        duration=10_000_000, seek_error=OSError("cannot seek")))

    data = generate_thumbnail(tmp_path / "stream.webm", max_dimension=64, video=True)

    assert data[8:12] == b"WEBP"


def test_generate_thumbnail_video_missing_pyav_raises(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "av", None)  # forces ImportError on `import av`
    with pytest.raises(ThumbError):
        generate_thumbnail(tmp_path / "clip.mp4", max_dimension=320, video=True)


def test_cache_path_stable(tmp_path):
    a = cache_path(tmp_path, "outputs", "img.png", 12345, 320)
    b = cache_path(tmp_path, "outputs", "img.png", 12345, 320)
    assert a == b
    assert a.suffix == ".webp"


def test_cache_path_mirrors_source_layout(tmp_path):
    p = cache_path(tmp_path, "outputs", "sub/deep/img.png", 12345, 320)
    assert p.parent == tmp_path / "outputs" / "sub" / "deep"


@pytest.mark.parametrize("other", [
    ("outputs", "img.png", 99999, 320),   # mtime
    ("outputs", "img.png", 12345, 256),   # max_dimension
    ("inputs", "img.png", 12345, 320),    # root id
    ("outputs", "other.png", 12345, 320), # name
])
def test_cache_path_differs(tmp_path, other):
    base = cache_path(tmp_path, "outputs", "img.png", 12345, 320)
    assert cache_path(tmp_path, *other) != base


def test_cache_path_survives_very_long_names(tmp_path):
    """Source names can approach the 255-byte limit; the cache entry adds
    metadata to the name, so it hashes the leaf rather than reusing it."""
    p = cache_path(tmp_path, "r", "a" * 250 + ".png", 1, 320)
    assert len(p.name.encode()) < 255


def test_cache_path_canonicalizes_dot_segments(tmp_path):
    a = cache_path(tmp_path, "r", "sub/./img.png", 123, 320)
    b = cache_path(tmp_path, "r", "sub/img.png", 123, 320)
    assert a == b


def test_invalidate_removes_all_variants_of_a_file(tmp_path):
    for mtime in (1, 2):
        p = cache_path(tmp_path, "r", "sub/img.png", mtime, 320)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"thumb")
    keep = cache_path(tmp_path, "r", "sub/other.png", 1, 320)
    keep.write_bytes(b"thumb")

    invalidate(tmp_path, "r", "sub/img.png")

    assert list(keep.parent.iterdir()) == [keep]


def test_invalidate_removes_a_whole_folder_subtree(tmp_path):
    inner = cache_path(tmp_path, "r", "album/2024/img.png", 1, 320)
    inner.parent.mkdir(parents=True, exist_ok=True)
    inner.write_bytes(b"thumb")

    invalidate(tmp_path, "r", "album")

    assert not (tmp_path / "r" / "album").exists()


def test_invalidate_is_a_noop_for_an_uncached_path(tmp_path):
    invalidate(tmp_path, "r", "never/cached.png")  # must not raise


def _seed(tmp_path, rel, mtime=1):
    p = cache_path(tmp_path, "r", rel, mtime, 320)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"thumb")
    return p


def test_prune_drops_entries_whose_source_vanished(tmp_path):
    """A file deleted outside FileManaty hits no eviction hook — prune is the
    only thing that stops its thumbnail from living forever."""
    gone = _seed(tmp_path, "pic.png")
    alive = _seed(tmp_path, "keep.png", mtime=7)

    prune(tmp_path, "r", "", {"keep.png": 7})

    assert not gone.exists()
    assert alive.exists()


def test_prune_drops_entries_whose_source_was_overwritten(tmp_path):
    """Same path, new mtime: the cached thumb holds the *previous* image."""
    stale = _seed(tmp_path, "pic.png", mtime=1)

    prune(tmp_path, "r", "", {"pic.png": 2})

    assert not stale.exists()


def test_prune_drops_mirror_dirs_for_deleted_folders(tmp_path):
    _seed(tmp_path, "album/pic.png")
    _seed(tmp_path, "kept/pic.png")

    prune(tmp_path, "r", "", {"kept": 0})

    assert not (tmp_path / "r" / "album").exists()
    assert (tmp_path / "r" / "kept").is_dir()


def test_prune_keeps_in_flight_temp_files(tmp_path):
    """A concurrent writer's staged temp belongs to a live source — pruning it
    mid-write would corrupt that request's atomic swap."""
    final = cache_path(tmp_path, "r", "pic.png", 5, 320)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_cache_path(final)
    tmp.write_bytes(b"staging")

    prune(tmp_path, "r", "", {"pic.png": 5})

    assert tmp.exists()


def test_prune_is_a_noop_without_a_mirror_dir(tmp_path):
    prune(tmp_path, "r", "nothing/here", {})  # must not raise


def test_tmp_cache_path_is_unique_per_call(tmp_path):
    """Two concurrent writers staging the same key must NOT share a temp path,
    otherwise their writes interleave and corrupt the file before .replace()."""
    final = cache_path(tmp_path, "r", "img.png", 1, 320)
    assert tmp_cache_path(final) != tmp_cache_path(final)


def test_tmp_cache_path_lives_beside_final_and_differs_from_it(tmp_path):
    final = cache_path(tmp_path, "r", "img.png", 1, 320)
    tmp = tmp_cache_path(final)
    assert tmp.parent == final.parent
    assert tmp != final
