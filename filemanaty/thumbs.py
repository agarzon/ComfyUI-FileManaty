"""Image thumbnail generation + on-disk WebP cache."""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

log = logging.getLogger("filemanaty")


class ThumbError(Exception):
    """Raised when a thumbnail cannot be generated."""


def generate_thumbnail(src: Path, max_dimension: int) -> bytes:
    """Generate a WebP thumbnail for ``src``, return raw bytes.

    Raises ``ThumbError`` on any failure (unsupported, corrupt, oversize).
    """
    try:
        with Image.open(src) as img:
            img.load()
            # Normalize odd modes (P, L, etc.) to RGB so Pillow can encode WebP.
            # RGB and RGBA are passed through; WebP supports both.
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=80)
            return buf.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ThumbError(f"cannot read image: {exc}") from exc
    except Exception as exc:
        # Pillow can raise DecompressionBombError, struct.error, zlib errors,
        # and other internal types on malformed input. Catch broadly; if a
        # programming bug ever shows up here, it'll appear in logs as
        # "thumbnail failed: ..." rather than crashing the request handler.
        raise ThumbError(f"thumbnail failed: {exc}") from exc


def cache_key(root_id: str, rel_path: str, mtime_ns: int, max_dimension: int) -> str:
    """Stable key for an on-disk thumb cache entry (first 16 hex chars of sha256)."""
    rel_path = PurePosixPath(rel_path).as_posix()
    raw = f"{root_id}:{rel_path}:{mtime_ns}:{max_dimension}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def cache_path(cache_dir: Path, key: str) -> Path:
    """Return the on-disk filename for a thumbnail with the given cache key."""
    return cache_dir / f"{key}.webp"
