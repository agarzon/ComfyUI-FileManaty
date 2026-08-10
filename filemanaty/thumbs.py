"""Image/video thumbnail generation + on-disk WebP cache."""
from __future__ import annotations

import hashlib
import io
import logging
import secrets
import shutil
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

log = logging.getLogger("filemanaty")

# Where in a clip to grab the thumbnail frame, as a fraction of its duration.
# Midpoint, not frame 0: intros fade in from black, so frame 0 is often a
# featureless rectangle.
# ponytail: fixed constant. Promote to `thumbnails.*` in config.json if anyone
# actually wants to tune it — the value would then have to join the cache-path
# filename, or changed settings would keep serving old frames.
VIDEO_FRAME_POSITION = 0.5


class ThumbError(Exception):
    """Raised when a thumbnail cannot be generated."""


def _video_frame(src: Path) -> Image.Image:
    """Decode one frame near ``VIDEO_FRAME_POSITION`` of ``src`` as a PIL image."""
    import av  # lazy: ComfyUI-core dep, may be absent in some installs

    with av.open(str(src)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        if container.duration:  # None on some streamed containers
            try:
                # `duration` is already in AV_TIME_BASE units, which is what the
                # container-level seek expects. Seeks land on the keyframe at or
                # before the target, so decoding from there yields a real frame.
                container.seek(int(container.duration * VIDEO_FRAME_POSITION))
            except Exception as exc:  # noqa: BLE001 - unseekable: settle for frame 0
                log.debug("filemanaty: seek failed for %s: %s", src.name, exc)
        for frame in container.decode(stream):
            return frame.to_image()
    raise ThumbError("no decodable video frames")


def generate_thumbnail(src: Path, max_dimension: int, video: bool = False) -> bytes:
    """Generate a WebP thumbnail for ``src``, return raw bytes.

    ``video`` picks the decoder: a mid-clip frame via PyAV instead of Pillow.
    Raises ``ThumbError`` on any failure (unsupported, corrupt, oversize).
    """
    try:
        with (_video_frame(src) if video else Image.open(src)) as img:
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


def _leaf_key(name: str) -> str:
    """Hashed stand-in for a file name: keeps cache entries within the 255-byte
    filename limit no matter how long the source name is."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def cache_path(
    cache_dir: Path, root_id: str, rel_path: str, mtime_ns: int, max_dimension: int
) -> Path:
    """On-disk path for a thumbnail, mirroring the source layout under ``root_id``.

    Mirroring (rather than one flat hash of everything) is what makes
    ``invalidate`` possible: a deleted source file or folder maps back to a
    known place in the cache. mtime/max_dimension live in the filename so a
    changed source is a cache miss, and all variants of one file share a prefix.
    """
    rel = PurePosixPath(rel_path)
    return (cache_dir / root_id / rel.parent
            / f"{_leaf_key(rel.name)}.{mtime_ns}.{max_dimension}.webp")


def tmp_cache_path(final: Path) -> Path:
    """A unique temp path for staging a thumbnail before atomic .replace().

    The random suffix (not the PID) is what makes this unique: two concurrent
    requests for the same uncached thumbnail run in the same process, so a
    PID-based name would collide and the two writers would corrupt each other's
    bytes before the swap. The final .replace() is atomic regardless.
    """
    return final.with_name(f"{final.name}.{secrets.token_hex(4)}.tmp")


def invalidate(cache_dir: Path, root_id: str, rel_path: str) -> None:
    """Drop every cached thumbnail for ``rel_path`` — a file, or a folder and
    everything under it. Called whenever source bytes are deleted or replaced:
    a thumbnail that outlives its source is a copy of data the user removed.
    """
    rel = PurePosixPath(rel_path)
    base = cache_dir / root_id / rel
    shutil.rmtree(base, ignore_errors=True)  # folder case; no-op for a file
    for entry in base.parent.glob(f"{_leaf_key(rel.name)}.*"):  # every variant
        entry.unlink(missing_ok=True)


def prune(cache_dir: Path, root_id: str, rel_dir: str, live: dict[str, int]) -> None:
    """Drop cache entries in one mirrored directory whose source no longer matches.

    ``live`` maps every name currently in the source directory to its mtime_ns,
    or 0 for a subdirectory. This is what catches changes FileManaty never saw:
    a file deleted or overwritten on disk hits no eviction hook, so its thumbnail
    would otherwise outlive it. Callers must pass a COMPLETE listing — a partial
    one would read as "these sources are gone" and evict valid entries.
    """
    mirror = cache_dir / root_id / PurePosixPath(rel_dir)
    if not mirror.is_dir():
        return
    # Entries are "<leaf_key>.<mtime_ns>.<max_dim>.webp"; subdirectories mirror
    # source folder names verbatim.
    by_leaf = {_leaf_key(name): str(mtime) for name, mtime in live.items()}
    for entry in mirror.iterdir():
        if entry.is_dir():
            if entry.name not in live:
                shutil.rmtree(entry, ignore_errors=True)
            continue
        leaf, _, rest = entry.name.partition(".")
        if by_leaf.get(leaf) != rest.partition(".")[0]:
            entry.unlink(missing_ok=True)
