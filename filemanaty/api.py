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

from filemanaty import operations as ops
from filemanaty.config import Config, RootConfig, load_config
from filemanaty.security import (
    PathEscapeError, has_hidden_component, safe_name, safe_resolve,
)
from filemanaty.thumbs import ThumbError, cache_key, cache_path, generate_thumbnail, tmp_cache_path

log = logging.getLogger("filemanaty")

API_PREFIX = "/filemanaty/api/v1"
MAX_LIST_ENTRIES = 5000
_VALID_ON_CONFLICT = (None, "skip", "replace", "keep_both")


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


def _resolve_dir(cfg: Config, root_id: str, raw_path: str) -> tuple[RootConfig, Path]:
    """Resolve a directory path inside a root. Raises PathEscapeError."""
    root = _find_root(cfg, root_id)
    target = safe_resolve(root.path, _strip_path(raw_path))
    return root, target


def _kind_for(name: str, path: Path, image_exts: tuple[str, ...]) -> str:
    if path.is_dir():
        return "folder"
    if path.suffix.lower() in image_exts:
        return "image"
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

    def scan() -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
        """Returns (entries, None) on success or (None, error_code) on filesystem error."""
        if not target.exists():
            return None, "NOT_FOUND"
        if not target.is_dir():
            return None, "NOT_A_DIR"
        out: list[dict[str, Any]] = []
        with os.scandir(target) as it:
            for entry in it:
                if _is_hidden(entry.name) and not include_hidden:
                    continue
                if len(out) > MAX_LIST_ENTRIES:
                    break
                try:
                    st = entry.stat()
                except OSError:
                    continue
                out.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": int(st.st_size),
                    "mtime": int(st.st_mtime),
                    "kind": _kind_for(entry.name, Path(entry.path), cfg.files.image_extensions),
                })
        return out, None

    entries, err_code = await loop.run_in_executor(None, scan)
    if err_code == "NOT_FOUND":
        return _err("NOT_FOUND", f"no such path: {raw_path!r}", 404)
    if err_code == "NOT_A_DIR":
        return _err("BAD_REQUEST", "list target must be a directory", 400)
    assert entries is not None
    truncated = len(entries) > MAX_LIST_ENTRIES
    entries = entries[:MAX_LIST_ENTRIES]

    rel = target.resolve().relative_to(root.path.resolve()).as_posix()
    if rel == ".":
        rel = ""
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
        rel = _strip_path(raw_path)
        root = _find_root(cfg, root_id)
        target = safe_resolve(root.path, rel)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)

    if not target.is_file():
        return _err("NOT_FOUND", "no such file", 404)

    if (resp := _reject_hidden(target, root.path)) is not None:
        return resp

    if target.suffix.lower() not in cfg.files.image_extensions:
        return _err("THUMB_UNSUPPORTED", "not an image extension", 404)

    mtime_ns = target.stat().st_mtime_ns
    key = cache_key(root_id, rel, mtime_ns, cfg.thumbnails.max_dimension)

    cache_dir = _thumb_cache_dir()
    out_path = cache_path(cache_dir, key)
    loop = asyncio.get_running_loop()

    def write_and_read() -> bytes:
        cache_dir.mkdir(parents=True, exist_ok=True)
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
            None, generate_thumbnail, target, cfg.thumbnails.max_dimension
        )
    except ThumbError as exc:
        log.info("filemanaty: thumb generation failed for %s: %s", target.name, exc)
        return _err("THUMB_UNSUPPORTED", "could not generate thumbnail", 404)

    def store(payload: bytes) -> None:
        # Unique per-call tmp name avoids two concurrent writers (same process)
        # fighting over one temp file. Replace is atomic; if a second writer
        # wins the race, the bytes are identical anyway.
        tmp = tmp_cache_path(cache_dir, key)
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
    if not attachment and target.suffix.lower() not in cfg.files.image_extensions:
        return _err("PREVIEW_UNSUPPORTED", "preview is image-only in v1", 404)
    return await _send_file(request, target, attachment=attachment)


async def _preview(request: web.Request) -> web.Response:
    return await _file_endpoint(request, attachment=False)


async def _download(request: web.Request) -> web.Response:
    return await _file_endpoint(request, attachment=True)


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
    return _ok({"status": "done", "name": target.name})


async def _trash_list(request: web.Request) -> web.Response:
    cfg = _get_config()
    root_id = request.query.get("root")
    if root_id is None:
        return _err("BAD_REQUEST", "missing 'root' query param", 400)
    try:
        root = _find_root(cfg, root_id)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, ops.list_trash, root.path)
    return _ok({"root": root_id, "items": items})


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


def attach_routes(app: web.Application) -> None:
    """Attach all routes to the given aiohttp Application."""
    app.router.add_get(f"{API_PREFIX}/roots", _roots)
    app.router.add_get(f"{API_PREFIX}/list", _list)
    app.router.add_get(f"{API_PREFIX}/thumbnail", _thumbnail)
    app.router.add_get(f"{API_PREFIX}/preview", _preview)
    app.router.add_get(f"{API_PREFIX}/download", _download)
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
    global _config
    _config = load_config(
        config_path=config_path,
        default_output_dir=Path(folder_paths.get_output_directory()),
        default_input_dir=Path(folder_paths.get_input_directory()),
    )

    log.info("filemanaty: loaded config from %s", config_path if config_path.exists() else "(defaults)")
    for r in _config.roots:
        log.info("filemanaty: root id=%s label=%s path=%s", r.id, r.label, r.path)

    attach_routes(PromptServer.instance.app)


# Side-effect on import: attach routes when ComfyUI loads this package.
# Python's module cache prevents double-import; do not call this twice manually
# (aiohttp's router rejects duplicate registrations).
_attach_to_promptserver()
