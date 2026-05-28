"""Config loading + validation for ComfyUI-FileManaty.

The config lives at <package_dir>/config.json. If the file is absent,
the loader synthesizes safe defaults that auto-mount ComfyUI's output
and input directories.

Single public entry point: ``load_config(config_path, default_output_dir,
default_input_dir) -> Config``. The caller (api.py at import time) is
responsible for supplying the ComfyUI defaults via ``folder_paths``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

log = logging.getLogger("filemanaty")

DEFAULT_IMAGE_EXTS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif",
)


@dataclass(frozen=True)
class RootConfig:
    id: str
    label: str
    path: Path
    writable: bool = True


@dataclass(frozen=True)
class FilesConfig:
    allow_hidden: bool = False
    image_extensions: tuple[str, ...] = DEFAULT_IMAGE_EXTS


@dataclass(frozen=True)
class ThumbnailsConfig:
    enabled: bool = True
    max_dimension: int = 320


@dataclass(frozen=True)
class WriteConfig:
    max_upload_mb: int = 1024


@dataclass(frozen=True)
class Config:
    roots: tuple[RootConfig, ...]
    files: FilesConfig
    thumbnails: ThumbnailsConfig
    write: WriteConfig = field(default_factory=WriteConfig)


def load_config(
    config_path: Path,
    default_output_dir: Path,
    default_input_dir: Path,
) -> Config:
    """Load config from ``config_path`` or synthesize defaults if absent."""
    if not config_path.exists():
        log.info("filemanaty: no config at %s, using auto-mount defaults", config_path)
        return _default_config(default_output_dir, default_input_dir)

    import json
    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        log.error("filemanaty: malformed config at %s: %s; using defaults", config_path, exc)
        return _default_config(default_output_dir, default_input_dir)

    try:
        return _parse_config(raw)
    except _ConfigError as exc:
        log.error("filemanaty: invalid config at %s: %s; using defaults", config_path, exc)
        return _default_config(default_output_dir, default_input_dir)


class _ConfigError(Exception):
    """Raised by _parse_config when the input is structurally invalid."""


def _parse_config(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise _ConfigError("top-level must be an object")
    roots_raw = raw.get("roots", [])
    if not isinstance(roots_raw, list):
        raise _ConfigError("'roots' must be a list")

    if len(roots_raw) == 0:
        log.warning("filemanaty: no roots configured in config file; UI will be empty")

    roots: list[RootConfig] = []
    seen_ids: set[str] = set()
    for entry in roots_raw:
        if not isinstance(entry, dict):
            raise _ConfigError("each root must be an object")
        rid = entry.get("id")
        label = entry.get("label")
        path_str = entry.get("path")
        if not isinstance(rid, str) or not isinstance(label, str) or not isinstance(path_str, str):
            raise _ConfigError(f"root missing id/label/path: {entry!r}")
        if not _ID_RE.match(rid):
            raise _ConfigError(f"root id {rid!r} does not match {_ID_RE.pattern}")
        if rid in seen_ids:
            raise _ConfigError(f"duplicate root id: {rid}")
        try:
            resolved = Path(path_str).resolve(strict=True)
        except OSError as exc:
            raise _ConfigError(f"root path does not exist: {path_str!r} ({exc})")
        if not resolved.is_dir():
            raise _ConfigError(f"root path is not a directory: {path_str!r}")
        seen_ids.add(rid)
        writable = bool(entry.get("writable", True))
        roots.append(RootConfig(id=rid, label=label, path=resolved, writable=writable))

    files_raw = raw.get("files", {})
    if not isinstance(files_raw, dict):
        raise _ConfigError(f"'files' must be an object, got {type(files_raw).__name__}")
    extensions = tuple(str(x).lower() for x in files_raw.get("image_extensions", DEFAULT_IMAGE_EXTS))
    for ext in extensions:
        if not ext.startswith("."):
            raise _ConfigError(f"image extension must start with '.': {ext!r}")
    files = FilesConfig(
        allow_hidden=bool(files_raw.get("allow_hidden", False)),
        image_extensions=extensions,
    )

    thumbs_raw = raw.get("thumbnails", {})
    if not isinstance(thumbs_raw, dict):
        raise _ConfigError(f"'thumbnails' must be an object, got {type(thumbs_raw).__name__}")
    try:
        max_dim = int(thumbs_raw.get("max_dimension", 320))
    except (TypeError, ValueError) as exc:
        raise _ConfigError(f"'thumbnails.max_dimension' must be an int: {exc}")
    if not 64 <= max_dim <= 1024:
        raise _ConfigError(f"thumbnails.max_dimension must be 64..1024, got {max_dim}")
    thumbnails = ThumbnailsConfig(
        enabled=bool(thumbs_raw.get("enabled", True)),
        max_dimension=max_dim,
    )

    write_raw = raw.get("write", {})
    if not isinstance(write_raw, dict):
        raise _ConfigError(f"'write' must be an object, got {type(write_raw).__name__}")
    try:
        max_upload = int(write_raw.get("max_upload_mb", 1024))
    except (TypeError, ValueError) as exc:
        raise _ConfigError(f"'write.max_upload_mb' must be an int: {exc}")
    if not 1 <= max_upload <= 1_048_576:
        raise _ConfigError(f"write.max_upload_mb must be 1..1048576, got {max_upload}")
    write = WriteConfig(max_upload_mb=max_upload)

    return Config(roots=tuple(roots), files=files, thumbnails=thumbnails, write=write)


def _default_config(output_dir: Path, input_dir: Path) -> Config:
    return Config(
        roots=(
            RootConfig(id="outputs", label="Outputs", path=output_dir.resolve()),
            RootConfig(id="inputs",  label="Inputs",  path=input_dir.resolve()),
        ),
        files=FilesConfig(),
        thumbnails=ThumbnailsConfig(),
    )
