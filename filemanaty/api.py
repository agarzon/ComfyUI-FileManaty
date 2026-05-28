"""HTTP API for ComfyUI-FileManaty.

At import time (when ComfyUI scans custom_nodes), this module calls
``_attach_to_promptserver`` to attach routes to ComfyUI's aiohttp app.
For tests, ``attach_routes(app)`` mounts the same routes on any app.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from filemanaty.config import Config, RootConfig, load_config
from filemanaty.security import PathEscapeError, has_hidden_component, safe_resolve
from filemanaty.thumbs import ThumbError, cache_key, cache_path, generate_thumbnail

log = logging.getLogger("filemanaty")

API_PREFIX = "/filemanaty/api/v1"
MAX_LIST_ENTRIES = 5000

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


def _err(code: str, message: str, status: int) -> web.Response:
    # Spec §9: INFO on 4xx with the raw input that triggered it; helps debug
    # user confusion without flooding logs on legit success paths.
    if 400 <= status < 500:
        log.info("filemanaty: %s -> %d %s", code, status, message)
    return web.json_response(
        {"ok": False, "data": None, "error": {"code": code, "message": message}},
        status=status,
    )


def _strip_path(raw: str) -> str:
    """Strip leading/trailing slashes and `./` from a relative path."""
    return raw.strip("/").strip("\\").removeprefix("./")


def _kind_for(name: str, path: Path, image_exts: tuple[str, ...]) -> str:
    if path.is_dir():
        return "folder"
    if path.suffix.lower() in image_exts:
        return "image"
    return "other"


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _reject_hidden(target: Path, root_path: Path, cfg: Config) -> Optional[web.Response]:
    """Return a 403 response if the target sits under any hidden path component."""
    if cfg.files.allow_hidden:
        return None
    if has_hidden_component(target, root_path):
        return _err("ACCESS_DENIED", "hidden files not allowed", 403)
    return None


async def _roots(request: web.Request) -> web.Response:
    cfg = _get_config()
    return _ok({"roots": [{"id": r.id, "label": r.label} for r in cfg.roots]})


async def _list(request: web.Request) -> web.Response:
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

    if (resp := _reject_hidden(target, root.path, cfg)) is not None:
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
                if _is_hidden(entry.name) and not cfg.files.allow_hidden:
                    continue
                if len(out) >= MAX_LIST_ENTRIES:
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
    truncated = len(entries) >= MAX_LIST_ENTRIES

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
    if not cfg.thumbnails.enabled:
        return _err("NOT_FOUND", "thumbnails disabled by config", 404)

    try:
        rel = _strip_path(raw_path)
        root = _find_root(cfg, root_id)
        target = safe_resolve(root.path, rel)
    except PathEscapeError as exc:
        return _err("ACCESS_DENIED", str(exc), 403)

    if not target.is_file():
        return _err("NOT_FOUND", "no such file", 404)

    if (resp := _reject_hidden(target, root.path, cfg)) is not None:
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
        # Per-request tmp name avoids two concurrent writers fighting over the
        # same `<key>.webp.tmp`. Replace is atomic; if a second writer wins the
        # race, the bytes are identical anyway.
        tmp = cache_dir / f"{key}.{os.getpid()}.tmp"
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
    if (resp := _reject_hidden(target, root.path, cfg)) is not None:
        return resp
    if not attachment and target.suffix.lower() not in cfg.files.image_extensions:
        return _err("PREVIEW_UNSUPPORTED", "preview is image-only in v1", 404)
    return await _send_file(request, target, attachment=attachment)


async def _preview(request: web.Request) -> web.Response:
    return await _file_endpoint(request, attachment=False)


async def _download(request: web.Request) -> web.Response:
    return await _file_endpoint(request, attachment=True)


def attach_routes(app: web.Application) -> None:
    """Attach all routes to the given aiohttp Application."""
    app.router.add_get(f"{API_PREFIX}/roots", _roots)
    app.router.add_get(f"{API_PREFIX}/list", _list)
    app.router.add_get(f"{API_PREFIX}/thumbnail", _thumbnail)
    app.router.add_get(f"{API_PREFIX}/preview", _preview)
    app.router.add_get(f"{API_PREFIX}/download", _download)


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
