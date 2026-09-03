"""HTTP API for ComfyUI-FileManaty.

At import time (when ComfyUI scans custom_nodes), this module calls
``_attach_to_promptserver`` to attach routes to ComfyUI's aiohttp app.
For tests, ``attach_routes(app)`` mounts the same routes on any app.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import mimetypes
import os
import secrets
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from filemanaty import metadata
from filemanaty import operations as ops
from filemanaty.config import Config, RootConfig, load_config
from filemanaty.security import (
    PathEscapeError, has_hidden_component, safe_name, safe_resolve,
)
from filemanaty.thumbs import (
    ThumbError, cache_path, generate_thumbnail, invalidate, prune, tmp_cache_path,
)

log = logging.getLogger("filemanaty")

API_PREFIX = "/filemanaty/api/v1"
MAX_LIST_ENTRIES = 5000
_VALID_ON_CONFLICT = (None, "skip", "replace", "keep_both")

# /zip takes one query param per item, so the cap is really about the request
# line the server will accept before it 414s — this refuses first, with a
# readable error instead of a raw protocol failure.
MAX_ZIP_ITEMS = 200


def _parse_bool(raw: Optional[str], *, default: bool) -> Optional[bool]:
    """Parse a query-param bool. Returns the bool, or None if ``raw`` is invalid.

    Accepts (case-insensitive): "true", "false", "1", "0". Anything else => None.
    A missing param (``raw is None``) returns ``default``.
    """
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


_config: Optional[Config] = None


def _get_config() -> Config:
    """Test seam — patched by tests."""
    if _config is None:
        raise RuntimeError("filemanaty config not initialized")
    return _config


def _thumb_cache_dir() -> Path:
    """Where on-disk thumb cache lives. Override via FILEMANATY_CACHE_DIR for tests."""
    env = os.environ.get("FILEMANATY_CACHE_DIR")
    if env:
        return Path(env)
    try:
        import folder_paths  # type: ignore
        user_dir = Path(folder_paths.get_user_directory())
        return user_dir / "filemanaty" / "thumbs"
    except ImportError:
        return Path(tempfile.gettempdir()) / "filemanaty" / "thumbs"


def _find_root(cfg: Config, root_id: str) -> RootConfig:
    for r in cfg.roots:
        if r.id == root_id:
            return r
    raise PathEscapeError(f"unknown root: {root_id!r}")


def _ok(data: Any) -> web.Response:
    return web.json_response({"ok": True, "data": data, "error": None})


def _err(code: str, message: str, status: int, **extra: Any) -> web.Response:
    if 400 <= status < 500:
        log.info("filemanaty: %s -> %d %s", code, status, message)
    err: dict[str, Any] = {**extra, "code": code, "message": message}
    return web.json_response({"ok": False, "data": None, "error": err}, status=status)


def _strip_path(raw: str) -> str:
    """Strip leading/trailing slashes and `./` from a relative path."""
    return raw.strip("/").strip("\\").removeprefix("./")


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _rel_to_root(root: RootConfig, target: Path) -> str:
    """Canonical posix path of ``target`` within ``root``. Callers pass paths
    that already went through safe_resolve, so containment is guaranteed."""
    return target.resolve().relative_to(root.path.resolve()).as_posix()


async def _drop_thumbs(root: RootConfig, target: Path) -> None:
    """Evict cached thumbnails for ``target`` after its bytes were removed or
    replaced — a thumbnail outliving its source leaks deleted image content."""
    await asyncio.get_running_loop().run_in_executor(
        None, invalidate, _thumb_cache_dir(), root.id, _rel_to_root(root, target))


def _resolve_dir(cfg: Config, root_id: str, raw_path: str) -> tuple[RootConfig, Path]:
    """Resolve a directory path inside a root. Raises PathEscapeError."""
    root = _find_root(cfg, root_id)
    target = safe_resolve(root.path, _strip_path(raw_path))
    return root, target


def _kind_for(
    name: str,
    path: Path,
    image_exts: tuple[str, ...],
    video_exts: tuple[str, ...] = (),
    audio_exts: tuple[str, ...] = (),
) -> str:
    if path.is_dir():
        return "folder"
    suffix = path.suffix.lower()
    if suffix in image_exts:
        return "image"
    if suffix in video_exts:
        return "video"
    if suffix in audio_exts:
        return "audio"
    return "other"


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _require_writable(root: RootConfig) -> Optional[web.Response]:
    """Return a 403 response if ``root`` is configured read-only."""
    if not root.writable:
        return _err("READ_ONLY", f"root {root.id!r} is read-only", 403)
    return None


def _reject_hidden(target: Path, root_path: Path) -> Optional[web.Response]:
    """Return a 403 response if the target sits under any hidden path component.

    This is defense-in-depth for non-listing endpoints. /list does its own
    include_hidden-aware gating and bypasses this helper.
    """
    if has_hidden_component(target, root_path):
        return _err("ACCESS_DENIED", "hidden files not allowed", 403)
    return None


async def _roots(request: web.Request) -> web.Response:
    cfg = _get_config()
    return _ok({"roots": [{"id": r.id, "label": r.label, "writable": r.writable} for r in cfg.roots]})


async def _about(request: web.Request) -> web.Response:
    from filemanaty import __version__
    return _ok({"version": __version__})


async def _list(request: web.Request) -> web.Response:
    root_id = request.query.get("root")
    raw_path = request.query.get("path")
    if root_id is None or raw_path is None:
        return _err("BAD_REQUEST", "missing 'root' or 'path' query param", 400)

    include_hidden = _parse_bool(request.query.get("include_hidden"), default=False)
    if include_hidden is None:
        return _err("BAD_REQUEST", "invalid include_hidden value", 400)

    cfg = _get_config()
    try:
        root = _find_root(cfg, root_id)
        target = safe_resolve(root.path, _strip_path(raw_path))
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)

    if not include_hidden and (resp := _reject_hidden(target, root.path)) is not None:
        return resp

    loop = asyncio.get_running_loop()

    def scan() -> tuple[Optional[list[dict[str, Any]]], dict[str, int], Optional[str]]:
        """Returns (entries, live, None) on success or (None, {}, error_code) on
        filesystem error. ``live`` is every name in the directory (hidden ones
        included) mapped to its mtime_ns, 0 for dirs — the input thumbs.prune
        needs to spot sources that changed behind our back."""
        if not target.exists():
            return None, {}, "NOT_FOUND"
        if not target.is_dir():
            return None, {}, "NOT_A_DIR"
        out: list[dict[str, Any]] = []
        live: dict[str, int] = {}
        with os.scandir(target) as it:
            for entry in it:
                if len(out) > MAX_LIST_ENTRIES:
                    break
                try:
                    st = entry.stat()
                except OSError:
                    continue
                is_dir = entry.is_dir()
                live[entry.name] = 0 if is_dir else st.st_mtime_ns
                if _is_hidden(entry.name) and not include_hidden:
                    continue
                out.append({
                    "name": entry.name,
                    "type": "dir" if is_dir else "file",
                    "size": int(st.st_size),
                    "mtime": int(st.st_mtime),
                    "kind": _kind_for(
                        entry.name, Path(entry.path), cfg.files.image_extensions,
                        cfg.files.video_extensions, cfg.files.audio_extensions),
                })
        return out, live, None

    entries, live, err_code = await loop.run_in_executor(None, scan)
    if err_code == "NOT_FOUND":
        return _err("NOT_FOUND", f"no such path: {raw_path!r}", 404)
    if err_code == "NOT_A_DIR":
        return _err("BAD_REQUEST", "list target must be a directory", 400)
    assert entries is not None
    truncated = len(entries) > MAX_LIST_ENTRIES
    entries = entries[:MAX_LIST_ENTRIES]

    rel = _rel_to_root(root, target)
    if rel == ".":
        rel = ""

    # Self-heal the thumb cache for this folder. Skipped when the scan stopped
    # early: an incomplete `live` would look like mass deletion to prune().
    if not truncated:
        await loop.run_in_executor(
            None, prune, _thumb_cache_dir(), root_id, rel, live)
    if rel == "":
        parent_field: Optional[str] = None
    elif "/" not in rel:
        parent_field = ""
    else:
        parent_field = rel.rsplit("/", 1)[0]

    return _ok({
        "root": root_id,
        "path": rel,
        "parent": parent_field,
        "entries": entries,
        "truncated": truncated,
    })


async def _thumbnail(request: web.Request) -> web.Response:
    root_id = request.query.get("root")
    raw_path = request.query.get("path")
    if root_id is None or raw_path is None:
        return _err("BAD_REQUEST", "missing 'root' or 'path' query param", 400)

    cfg = _get_config()

    try:
        root = _find_root(cfg, root_id)
        target = safe_resolve(root.path, _strip_path(raw_path))
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    # Canonical rel — must match what _drop_thumbs derives, or eviction misses.
    rel = _rel_to_root(root, target)

    if not target.is_file():
        return _err("NOT_FOUND", "no such file", 404)

    if (resp := _reject_hidden(target, root.path)) is not None:
        return resp

    suffix = target.suffix.lower()
    is_video = suffix in cfg.files.video_extensions
    if not is_video and suffix not in cfg.files.image_extensions:
        return _err("THUMB_UNSUPPORTED", "not an image or video extension", 404)

    mtime_ns = target.stat().st_mtime_ns
    out_path = cache_path(
        _thumb_cache_dir(), root_id, rel, mtime_ns, cfg.thumbnails.max_dimension)
    loop = asyncio.get_running_loop()

    def write_and_read() -> bytes:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            return out_path.read_bytes()
        return b""  # caller will generate then call store_and_return

    cached = await loop.run_in_executor(None, write_and_read)
    if cached:
        return web.Response(
            body=cached,
            content_type="image/webp",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    try:
        data = await loop.run_in_executor(
            None, generate_thumbnail, target, cfg.thumbnails.max_dimension, is_video
        )
    except ThumbError as exc:
        log.info("filemanaty: thumb generation failed for %s: %s", target.name, exc)
        return _err("THUMB_UNSUPPORTED", "could not generate thumbnail", 404)

    def store(payload: bytes) -> None:
        # Unique per-call tmp name avoids two concurrent writers (same process)
        # fighting over one temp file. Replace is atomic; if a second writer
        # wins the race, the bytes are identical anyway.
        tmp = tmp_cache_path(out_path)
        tmp.write_bytes(payload)
        tmp.replace(out_path)

    await loop.run_in_executor(None, store, data)

    return web.Response(
        body=data,
        content_type="image/webp",
        headers={"Cache-Control": "private, max-age=3600"},
    )


async def _stream_file(target: Path, *, attachment_name: str | None) -> web.StreamResponse:
    """Construct a StreamResponse with the right headers for ``target``."""
    ctype, _ = mimetypes.guess_type(str(target))
    if ctype is None:
        ctype = "application/octet-stream"

    headers = {"Content-Type": ctype, "X-Content-Type-Options": "nosniff"}
    if attachment_name is not None:
        safe_legacy = attachment_name.replace("\\", "\\\\").replace('"', '\\"')
        safe_pct = urllib.parse.quote(attachment_name)
        headers["Content-Disposition"] = (
            f'attachment; filename="{safe_legacy}"; filename*=UTF-8\'\'{safe_pct}'
        )

    response = web.StreamResponse(status=200, headers=headers)
    return response


async def _send_file(request: web.Request, target: Path, *, attachment: bool) -> web.StreamResponse:
    """Common implementation for /preview and /download.

    Streams the file in 64K chunks. The initial open() and every read() run
    via the executor so the aiohttp loop stays responsive on slow filesystems.
    """
    response = await _stream_file(target, attachment_name=target.name if attachment else None)
    await response.prepare(request)
    loop = asyncio.get_running_loop()
    CHUNK = 64 * 1024

    f = await loop.run_in_executor(None, target.open, "rb")
    try:
        while True:
            chunk = await loop.run_in_executor(None, f.read, CHUNK)
            if not chunk:
                break
            await response.write(chunk)
    finally:
        await loop.run_in_executor(None, f.close)
    await response.write_eof()
    return response


async def _file_endpoint(request: web.Request, *, attachment: bool) -> web.Response:
    root_id = request.query.get("root")
    raw_path = request.query.get("path")
    if root_id is None or raw_path is None:
        return _err("BAD_REQUEST", "missing 'root' or 'path' query param", 400)
    cfg = _get_config()
    try:
        root = _find_root(cfg, root_id)
        target = safe_resolve(root.path, _strip_path(raw_path))
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if not target.is_file():
        return _err("NOT_FOUND", "no such file", 404)
    if (resp := _reject_hidden(target, root.path)) is not None:
        return resp
    if not attachment:
        suffix = target.suffix.lower()
        media_exts = cfg.files.video_extensions + cfg.files.audio_extensions
        if suffix not in cfg.files.image_extensions and suffix not in media_exts:
            return _err("PREVIEW_UNSUPPORTED", "preview is not supported for this file type", 404)
        # Video/audio need HTTP Range (seeking, Safari) — FileResponse handles 206
        # natively. Images keep the chunked streamer. nosniff stays on either path.
        if suffix in media_exts:
            return web.FileResponse(target, headers={"X-Content-Type-Options": "nosniff"})
    return await _send_file(request, target, attachment=attachment)


async def _preview(request: web.Request) -> web.Response:
    return await _file_endpoint(request, attachment=False)


async def _download(request: web.Request) -> web.Response:
    return await _file_endpoint(request, attachment=True)


async def _zip(request: web.Request) -> web.Response:
    """Download a selection as one archive.

    A GET so the browser's own download manager handles it, and the archive is
    built to a temp file before a byte is sent: that yields a real
    Content-Length, which is what makes the browser show bytes, speed and ETA.
    The cost is a silent wait while it builds, and the temp file, which is
    unlinked once the response is written.
    """
    cfg = _get_config()
    root_id = request.query.get("root")
    items = request.query.getall("path", [])
    if root_id is None or not items:
        return _err("BAD_REQUEST", "missing 'root' or 'path' query param", 400)
    if len(items) > MAX_ZIP_ITEMS:
        return _err("BAD_REQUEST", f"cannot zip more than {MAX_ZIP_ITEMS} items at once", 400)
    try:
        root = _find_root(cfg, root_id)
        targets = [safe_resolve(root.path, _strip_path(s)) for s in items]
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    for t in targets:
        if _is_trash_path(t, root.path):
            return _err("ACCESS_DENIED", "cannot zip the trash directory", 403)
        if (resp := _reject_hidden(t, root.path)) is not None:
            return resp
        if not t.exists():
            return _err("NOT_FOUND", f"no such item: {t.name}", 404)

    if len(targets) == 1:
        zip_name = f"{targets[0].name}.zip"
    else:
        zip_name = f"{targets[0].parent.name or root.id}.zip"

    loop = asyncio.get_running_loop()
    tmp = Path(tempfile.gettempdir()) / f"filemanaty-{secrets.token_hex(8)}.zip"
    try:
        try:
            await loop.run_in_executor(
                None, functools.partial(ops.write_zip, root.path, targets, tmp))
        except OSError as exc:
            log.info("filemanaty: zip build failed for root %s: %s", root.id, exc)
            return _err("IO_ERROR", "could not build the archive", 500)

        response = await _stream_file(tmp, attachment_name=zip_name)
        response.content_length = tmp.stat().st_size   # no Content-Length, no browser progress
        await response.prepare(request)
        f = await loop.run_in_executor(None, tmp.open, "rb")
        try:
            while True:
                chunk = await loop.run_in_executor(None, f.read, 64 * 1024)
                if not chunk:
                    break
                await response.write(chunk)
        finally:
            await loop.run_in_executor(None, f.close)
        await response.write_eof()
        return response
    finally:
        await loop.run_in_executor(None, functools.partial(tmp.unlink, missing_ok=True))


async def _metadata(request: web.Request) -> web.Response:
    root_id = request.query.get("root")
    raw_path = request.query.get("path")
    if root_id is None or raw_path is None:
        return _err("BAD_REQUEST", "missing 'root' or 'path' query param", 400)
    cfg = _get_config()
    try:
        root = _find_root(cfg, root_id)
        target = safe_resolve(root.path, _strip_path(raw_path))
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if not target.is_file():
        return _err("NOT_FOUND", "no such file", 404)
    if (resp := _reject_hidden(target, root.path)) is not None:
        return resp
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, metadata.extract, target)
    prompt = raw.get("prompt") if raw else None
    return _ok({"fields": metadata.summarize(prompt), "raw": raw})


async def _mkdir(request: web.Request) -> web.Response:
    cfg = _get_config()
    body = await _json_body(request)
    root_id, raw_path, name = body.get("root"), body.get("path"), body.get("name")
    on_conflict = body.get("on_conflict")
    if not isinstance(root_id, str) or not isinstance(raw_path, str) or not isinstance(name, str):
        return _err("BAD_REQUEST", "missing 'root', 'path', or 'name'", 400)
    if on_conflict not in _VALID_ON_CONFLICT:
        return _err("BAD_REQUEST", "invalid on_conflict value", 400)
    try:
        root, parent = _resolve_dir(cfg, root_id, raw_path)
        safe_name(name)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if (resp := _require_writable(root)) is not None:
        return resp
    if _is_trash_path(parent / name, root.path):
        return _err("ACCESS_DENIED", "cannot modify the trash directory", 403)
    if (resp := _reject_hidden(parent, root.path)) is not None:
        return resp
    if not parent.is_dir():
        return _err("BAD_REQUEST", "parent path is not a directory", 400)

    loop = asyncio.get_running_loop()
    target, status = await loop.run_in_executor(
        None, functools.partial(ops.resolve_collision, parent, name, on_conflict, is_dir=True))
    if status == "conflict":
        return _err("CONFLICT", "folder already exists", 409, conflicts=[name])
    if status == "skip":
        return _ok({"status": "skipped", "name": name})
    try:
        await loop.run_in_executor(
            None, functools.partial(ops.make_dir, parent, target.name, exist_ok=status == "replace"))
    except FileExistsError:
        return _err("CONFLICT", "folder already exists", 409, conflicts=[target.name])
    return _ok({"status": "done", "name": target.name})


async def _transfer(request: web.Request, *, move: bool) -> web.Response:
    """Shared copy/move handler. Validates src+dst roots, applies one
    on_conflict policy to all items, returns per-item results."""
    cfg = _get_config()
    body = await _json_body(request)
    src_root_id = body.get("src_root")
    dst_root_id = body.get("dst_root")
    src_items = body.get("src_items")
    dst_path = body.get("dst_path")
    on_conflict = body.get("on_conflict")
    if (not isinstance(src_root_id, str) or not isinstance(dst_root_id, str)
            or not isinstance(dst_path, str) or not isinstance(src_items, list)
            or not all(isinstance(s, str) for s in src_items)):
        return _err("BAD_REQUEST", "missing/invalid transfer fields", 400)
    if on_conflict not in _VALID_ON_CONFLICT:
        return _err("BAD_REQUEST", "invalid on_conflict value", 400)
    try:
        src_root = _find_root(cfg, src_root_id)
        dst_root, dst_dir = _resolve_dir(cfg, dst_root_id, dst_path)
        srcs = [safe_resolve(src_root.path, _strip_path(s)) for s in src_items]
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    # Copy writes only to the destination; move also removes from the source,
    # so a move out of a read-only root is itself a write to that root.
    if (resp := _require_writable(dst_root)) is not None:
        return resp
    if move and (resp := _require_writable(src_root)) is not None:
        return resp
    if not dst_dir.is_dir():
        return _err("BAD_REQUEST", "destination is not a directory", 400)
    if _is_trash_path(dst_dir, dst_root.path):
        return _err("ACCESS_DENIED", "cannot modify the trash directory", 403)
    if (resp := _reject_hidden(dst_dir, dst_root.path)) is not None:
        return resp
    for src in srcs:
        if _is_trash_path(src, src_root.path):
            return _err("ACCESS_DENIED", "cannot modify the trash directory", 403)
        if (resp := _reject_hidden(src, src_root.path)) is not None:
            return resp
        if src.resolve() == src_root.path.resolve():
            return _err("ACCESS_DENIED", "cannot transfer a root", 403)
        if not src.exists():
            return _err("NOT_FOUND", f"no such item: {src.name}", 404)
        if ops.is_descendant(dst_dir, src):
            return _err("BAD_REQUEST", "cannot copy or move a folder into itself", 400)

    loop = asyncio.get_running_loop()
    # First pass: detect conflicts when no policy was given.
    conflicts: list[str] = []
    plan: list[tuple[Path, Optional[Path], str]] = []  # (src, target_or_None, status)
    for src in srcs:
        target, status = await loop.run_in_executor(
            None, functools.partial(ops.resolve_collision, dst_dir, src.name, on_conflict, is_dir=src.is_dir()))
        if status == "conflict":
            conflicts.append(src.name)
        else:
            plan.append((src, target, status))
    if conflicts:
        return _err("CONFLICT", "targets already exist", 409, conflicts=conflicts)

    # Refuse a batch where two items would land on the same destination name —
    # otherwise the second silently overwrites the first.
    seen_targets: set[Path] = set()
    for _src, target, status in plan:
        if status == "skip":
            continue
        if target in seen_targets:
            return _err("CONFLICT", "multiple items map to the same destination name",
                        409, conflicts=[target.name])
        seen_targets.add(target)

    results: list[dict[str, Any]] = []
    op = ops.move_one if move else ops.copy_one
    for src, target, status in plan:
        if status == "skip":
            results.append({"name": src.name, "status": "skipped"})
            continue
        try:
            await loop.run_in_executor(
                None, functools.partial(op, src, target, replace=status == "replace"))
            if move:
                await _drop_thumbs(src_root, src)
            if status == "replace":
                await _drop_thumbs(dst_root, target)
            results.append({"name": target.name, "status": "done"})
        except OSError as exc:
            log.info("filemanaty: transfer failed for %s: %s", src.name, exc)
            results.append({"name": src.name, "status": "error", "message": str(exc)})
    return _ok({"results": results})


async def _copy(request: web.Request) -> web.Response:
    return await _transfer(request, move=False)


async def _move(request: web.Request) -> web.Response:
    return await _transfer(request, move=True)


def _is_trash_path(target: Path, root_path: Path) -> bool:
    try:
        rel = target.resolve().relative_to(root_path.resolve())
    except ValueError:
        return False
    return ops.TRASH_DIRNAME in rel.parts


async def _delete(request: web.Request) -> web.Response:
    cfg = _get_config()
    body = await _json_body(request)
    root_id = body.get("root")
    items = body.get("items")
    permanent = bool(body.get("permanent", False))
    if not isinstance(root_id, str) or not isinstance(items, list) or not all(isinstance(s, str) for s in items):
        return _err("BAD_REQUEST", "missing/invalid 'root' or 'items'", 400)
    try:
        root = _find_root(cfg, root_id)
        targets = [safe_resolve(root.path, _strip_path(s)) for s in items]
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if (resp := _require_writable(root)) is not None:
        return resp
    for t in targets:
        if t.resolve() == root.path.resolve():
            return _err("ACCESS_DENIED", "cannot delete a root", 403)
        if _is_trash_path(t, root.path):
            return _err("ACCESS_DENIED", "cannot delete the trash via /delete", 403)
        if (resp := _reject_hidden(t, root.path)) is not None:
            return resp
        if not t.exists():
            return _err("NOT_FOUND", f"no such item: {t.name}", 404)

    loop = asyncio.get_running_loop()
    results: list[dict[str, Any]] = []
    for t in targets:
        try:
            if permanent:
                await loop.run_in_executor(None, ops.delete_permanent, t)
                results.append({"name": t.name, "status": "deleted"})
            else:
                tid = await loop.run_in_executor(
                    None, functools.partial(ops.move_to_trash, root.path, t))
                results.append({"name": t.name, "status": "trashed", "id": tid})
            await _drop_thumbs(root, t)
        except OSError as exc:
            log.info("filemanaty: delete failed for %s: %s", t.name, exc)
            results.append({"name": t.name, "status": "error", "message": str(exc)})
    return _ok({"results": results})


async def _rename(request: web.Request) -> web.Response:
    cfg = _get_config()
    body = await _json_body(request)
    root_id, raw_path, name = body.get("root"), body.get("path"), body.get("name")
    on_conflict = body.get("on_conflict")
    if not isinstance(root_id, str) or not isinstance(raw_path, str) or not isinstance(name, str):
        return _err("BAD_REQUEST", "missing 'root', 'path', or 'name'", 400)
    if on_conflict not in _VALID_ON_CONFLICT:
        return _err("BAD_REQUEST", "invalid on_conflict value", 400)
    try:
        root = _find_root(cfg, root_id)
        src = safe_resolve(root.path, _strip_path(raw_path))
        safe_name(name)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if (resp := _require_writable(root)) is not None:
        return resp
    if src.resolve() == root.path.resolve():
        return _err("ACCESS_DENIED", "cannot rename a root", 403)
    if _is_trash_path(src, root.path) or _is_trash_path(src.parent / name, root.path):
        return _err("ACCESS_DENIED", "cannot modify the trash directory", 403)
    if not src.exists():
        return _err("NOT_FOUND", "no such item", 404)
    if (resp := _reject_hidden(src, root.path)) is not None:
        return resp

    loop = asyncio.get_running_loop()
    target, status = await loop.run_in_executor(
        None, functools.partial(ops.resolve_collision, src.parent, name, on_conflict, is_dir=src.is_dir()))
    if status == "conflict":
        return _err("CONFLICT", "target name already exists", 409, conflicts=[name])
    if status == "skip":
        return _ok({"status": "skipped", "name": src.name})
    try:
        await loop.run_in_executor(
            None, functools.partial(ops.rename, src, target, replace=status == "replace"))
    except OSError as exc:
        log.info("filemanaty: rename failed for %s -> %s: %s", src.name, target.name, exc)
        return _err("IO_ERROR", "rename failed", 409)
    await _drop_thumbs(root, src)  # old path no longer exists
    if status == "replace":        # the clobbered target's old bytes are gone
        await _drop_thumbs(root, target)
    return _ok({"status": "done", "name": target.name})


async def _trash_list(request: web.Request) -> web.Response:
    """One unified trash listing across every root, newest first.

    Storage stays per-root (like a per-volume .Trashes) so trashing and
    restoring are same-filesystem renames; each item carries its root id so
    restore/purge can route back to it.
    """
    cfg = _get_config()
    loop = asyncio.get_running_loop()
    # scanned concurrently: a root on a slow/network mount shouldn't stack its
    # latency on top of every other root's
    per_root = await asyncio.gather(*(
        loop.run_in_executor(None, ops.list_trash, root.path) for root in cfg.roots))
    items = [{**item, "root": root.id}
             for root, entries in zip(cfg.roots, per_root) for item in entries]
    items.sort(key=lambda i: i.get("deleted_at") or "", reverse=True)
    return _ok({"items": items})


async def _trash_restore(request: web.Request) -> web.Response:
    cfg = _get_config()
    body = await _json_body(request)
    root_id = body.get("root")
    ids = body.get("ids")
    on_conflict = body.get("on_conflict")
    if not isinstance(root_id, str) or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return _err("BAD_REQUEST", "missing/invalid 'root' or 'ids'", 400)
    if on_conflict not in _VALID_ON_CONFLICT:
        return _err("BAD_REQUEST", "invalid on_conflict value", 400)
    try:
        root = _find_root(cfg, root_id)
        for tid in ids:
            safe_name(tid)  # ids contain only digits, '-', hex — no separators/dots
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if (resp := _require_writable(root)) is not None:
        return resp
    ids = list(dict.fromkeys(ids))  # dedupe; a tid restored once must not be processed twice

    loop = asyncio.get_running_loop()
    conflicts: list[str] = []
    plan: list[tuple[str, Optional[Path], str]] = []  # (tid, target, status)
    for tid in ids:
        try:
            meta = await loop.run_in_executor(None, functools.partial(ops.trash_meta, root.path, tid))
            stored = await loop.run_in_executor(None, functools.partial(ops.trash_item_path, root.path, tid))
        except (FileNotFoundError, OSError, ValueError):
            return _err("NOT_FOUND", f"no such trash id: {tid}", 404)
        try:
            safe_name(meta["original_name"], allow_hidden=True)
        except PathEscapeError:
            return _err("ACCESS_DENIED", f"unsafe stored name for trash id: {tid}", 403)
        try:
            target = safe_resolve(root.path, _strip_path(meta["original_rel_path"]))
        except PathEscapeError as exc:
            return _err("ACCESS_DENIED", str(exc), 403)
        chosen, status = await loop.run_in_executor(
            None, functools.partial(ops.resolve_collision, target.parent, meta["original_name"], on_conflict, is_dir=stored.is_dir()))
        if status == "conflict":
            conflicts.append(meta["original_name"])
        else:
            plan.append((tid, chosen, status))
    if conflicts:
        return _err("CONFLICT", "restore targets already exist", 409, conflicts=conflicts)

    seen_targets: set[Path] = set()
    for _tid, target, status in plan:
        if status == "skip":
            continue
        if target in seen_targets:
            return _err("CONFLICT", "multiple trash items map to the same destination name",
                        409, conflicts=[target.name])
        seen_targets.add(target)

    results: list[dict[str, Any]] = []
    for tid, target, status in plan:
        if status == "skip":
            results.append({"id": tid, "status": "skipped"})
            continue
        await loop.run_in_executor(
            None, functools.partial(ops.restore_from_trash, root.path, tid, target, replace=status == "replace"))
        if status == "replace":
            await _drop_thumbs(root, target)
        results.append({"id": tid, "status": "restored", "name": target.name})
    return _ok({"results": results})


async def _trash_purge(request: web.Request) -> web.Response:
    cfg = _get_config()
    body = await _json_body(request)
    root_id = body.get("root")
    ids = body.get("ids")
    purge_everything = bool(body.get("all", False))
    if not isinstance(root_id, str):
        return _err("BAD_REQUEST", "missing 'root'", 400)
    try:
        root = _find_root(cfg, root_id)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    if (resp := _require_writable(root)) is not None:
        return resp
    loop = asyncio.get_running_loop()
    if purge_everything:
        await loop.run_in_executor(None, ops.purge_all, root.path)
        return _ok({"status": "emptied"})
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return _err("BAD_REQUEST", "missing/invalid 'ids'", 400)
    try:
        for tid in ids:
            safe_name(tid)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    for tid in ids:
        await loop.run_in_executor(None, functools.partial(ops.purge, root.path, tid))
    return _ok({"status": "purged", "count": len(ids)})


async def _upload(request: web.Request) -> web.Response:
    cfg = _get_config()
    max_bytes = cfg.write.max_upload_mb * 1024 * 1024
    on_conflict = request.query.get("on_conflict")
    if on_conflict not in _VALID_ON_CONFLICT:
        return _err("BAD_REQUEST", "invalid on_conflict value", 400)
    try:
        reader = await request.multipart()
    except Exception:
        return _err("BAD_REQUEST", "expected multipart/form-data", 400)

    root_id: Optional[str] = None
    dst_dir: Optional[Path] = None
    root: Optional[RootConfig] = None
    results: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()

    async for part in reader:
        if part.name == "root":
            root_id = (await part.text()).strip()
        elif part.name == "path":
            raw_path = await part.text()
            if root_id is None:
                return _err("BAD_REQUEST", "'root' field must precede 'path'", 400)
            try:
                root, dst_dir = _resolve_dir(cfg, root_id, raw_path)
            except PathEscapeError as exc:
                return _err("ACCESS_DENIED", str(exc), 403)
            if (resp := _require_writable(root)) is not None:
                return resp
            if _is_trash_path(dst_dir, root.path):
                return _err("ACCESS_DENIED", "cannot modify the trash directory", 403)
            if (resp := _reject_hidden(dst_dir, root.path)) is not None:
                return resp
            if not dst_dir.is_dir():
                return _err("BAD_REQUEST", "upload target is not a directory", 400)
        elif part.name == "file":
            if dst_dir is None or root is None:
                return _err("BAD_REQUEST", "'root'/'path' must precede file parts", 400)
            filename = part.filename or ""
            try:
                safe_name(filename)
            except PathEscapeError as exc:
                return _err("ACCESS_DENIED", str(exc), 403)
            target, status = await loop.run_in_executor(
                None, functools.partial(ops.resolve_collision, dst_dir, filename, on_conflict, is_dir=False))
            if status == "conflict":
                return _err("CONFLICT", "file already exists", 409, conflicts=[filename])
            if status == "skip":
                results.append({"name": filename, "status": "skipped"})
                continue
            if target.is_dir():
                return _err("BAD_REQUEST",
                            "upload target conflicts with an existing directory", 400)

            tmp = dst_dir / f".upload-{secrets.token_hex(4)}.part"
            size = 0
            too_large = False
            committed = False
            try:
                f = await loop.run_in_executor(None, tmp.open, "wb")
                try:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            too_large = True
                            break
                        await loop.run_in_executor(None, f.write, chunk)
                finally:
                    await loop.run_in_executor(None, f.close)
                if too_large:
                    return _err("UPLOAD_TOO_LARGE",
                                f"file exceeds {cfg.write.max_upload_mb} MB", 413)
                await loop.run_in_executor(
                    None, functools.partial(ops.rename, tmp, target, replace=status == "replace"))
                committed = True
                if status == "replace":
                    await _drop_thumbs(root, target)
            except OSError as exc:
                log.info("filemanaty: upload write failed for %s: %s", filename, exc)
                return _err("IO_ERROR", "upload write failed", 409)
            finally:
                if not committed:
                    await loop.run_in_executor(None, functools.partial(tmp.unlink, missing_ok=True))
            results.append({"name": target.name, "status": "done"})

    if not results:
        return _err("BAD_REQUEST", "no file parts in upload", 400)
    return _ok({"results": results})


def _purge_legacy_cache() -> None:
    """Drop flat ``<hash>.webp`` entries from the pre-mirror cache layout — it
    couldn't map a deleted source file back to its thumbnail, so nothing there
    was ever evictable."""
    try:
        for stale in _thumb_cache_dir().glob("*.webp"):
            stale.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("filemanaty: could not purge legacy thumb cache: %s", exc)


def attach_routes(app: web.Application) -> None:
    """Attach all routes to the given aiohttp Application."""
    _purge_legacy_cache()
    app.router.add_get(f"{API_PREFIX}/about", _about)
    app.router.add_get(f"{API_PREFIX}/roots", _roots)
    app.router.add_get(f"{API_PREFIX}/list", _list)
    app.router.add_get(f"{API_PREFIX}/thumbnail", _thumbnail)
    app.router.add_get(f"{API_PREFIX}/preview", _preview)
    app.router.add_get(f"{API_PREFIX}/download", _download)
    app.router.add_get(f"{API_PREFIX}/zip", _zip)
    app.router.add_get(f"{API_PREFIX}/metadata", _metadata)
    app.router.add_post(f"{API_PREFIX}/upload", _upload)
    app.router.add_post(f"{API_PREFIX}/mkdir", _mkdir)
    app.router.add_post(f"{API_PREFIX}/rename", _rename)
    app.router.add_post(f"{API_PREFIX}/copy", _copy)
    app.router.add_post(f"{API_PREFIX}/move", _move)
    app.router.add_post(f"{API_PREFIX}/delete", _delete)
    app.router.add_get(f"{API_PREFIX}/trash/list", _trash_list)
    app.router.add_post(f"{API_PREFIX}/trash/restore", _trash_restore)
    app.router.add_post(f"{API_PREFIX}/trash/purge", _trash_purge)


def _attach_to_promptserver() -> None:
    """Locate ComfyUI's PromptServer at import time and attach routes."""
    try:
        from server import PromptServer  # type: ignore
        import folder_paths  # type: ignore
    except ImportError:
        # Importable outside ComfyUI (e.g., during pytest collection).
        log.debug("filemanaty: PromptServer/folder_paths not importable; skipping route attach")
        return

    package_dir = Path(__file__).resolve().parent.parent
    config_path = package_dir / "config.json"
    # ComfyUI's single-user workflows dir; resolved via folder_paths so it's correct on
    # Windows/macOS/Linux and honors --user-directory. Guarded: never crash ComfyUI.
    try:
        workflows_dir = Path(folder_paths.get_user_directory()) / "default" / "workflows"
    except Exception:  # pragma: no cover - depends on ComfyUI runtime
        workflows_dir = None

    global _config
    _config = load_config(
        config_path=config_path,
        default_output_dir=Path(folder_paths.get_output_directory()),
        default_input_dir=Path(folder_paths.get_input_directory()),
        default_workflows_dir=workflows_dir,
    )

    log.info("filemanaty: loaded config from %s", config_path if config_path.exists() else "(defaults)")
    for r in _config.roots:
        log.info("filemanaty: root id=%s label=%s path=%s", r.id, r.label, r.path)

    attach_routes(PromptServer.instance.app)


# Side-effect on import: attach routes when ComfyUI loads this package.
# Python's module cache prevents double-import; do not call this twice manually
# (aiohttp's router rejects duplicate registrations).
_attach_to_promptserver()
