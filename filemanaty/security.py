"""Path-safety chokepoint.

Every API handler that accepts a user-supplied relative path MUST funnel
through ``safe_resolve``. Do not call ``Path.resolve`` or
``os.path.join`` with user input anywhere else in the package.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path


class PathEscapeError(PermissionError):
    """Raised when a user-supplied path escapes its configured root."""


class UnsafeNameError(PathEscapeError):
    """Raised when a user-supplied single path component (name) is unsafe."""


_UNSAFE_NAME_CHARS = frozenset("/\\\x00")


def safe_name(name: str, *, allow_hidden: bool = False) -> str:
    """Validate a single new path component (file/folder name).

    Rejects: empty, '.', '..', names containing '/', '\\' or NUL, names with
    leading/trailing whitespace, names ending in '.', and (unless
    ``allow_hidden``) names beginning with a dot. Returns ``name`` unchanged.
    """
    if not name or name in (".", ".."):
        raise UnsafeNameError(f"invalid name: {name!r}")
    if any(c in _UNSAFE_NAME_CHARS or unicodedata.category(c) == "Cc" for c in name):
        raise UnsafeNameError(f"name contains a path separator or control character: {name!r}")
    if name.startswith(".") and not allow_hidden:
        raise UnsafeNameError(f"hidden name not allowed: {name!r}")
    if name != name.strip() or name.endswith("."):
        raise UnsafeNameError(f"name has leading/trailing whitespace or trailing dot: {name!r}")
    return name


def safe_resolve(root_path: Path, rel: str) -> Path:
    """Resolve ``rel`` against ``root_path``, refusing escape attempts.

    Refuses:
      * absolute paths (Unix ``/...`` or Windows ``\\...`` / ``C:...``)
      * paths containing NUL bytes
      * paths that resolve outside ``root_path`` via ``..`` or symlinks

    Returns the canonical absolute Path inside ``root_path``.
    """
    if rel is None:
        raise PathEscapeError("relative path is None")
    if "\x00" in rel:
        raise PathEscapeError("path contains NUL byte")
    if rel.startswith("/") or rel.startswith("\\"):
        raise PathEscapeError("absolute path not allowed")
    # Windows drive markers ("C:", "C:foo") and UNC starts ("\\?\")
    if len(rel) >= 2 and rel[1] == ":":
        raise PathEscapeError("drive letter not allowed")

    root_real = root_path.resolve(strict=True)
    if not rel:
        return root_real

    candidate = (root_real / rel).resolve(strict=False)
    try:
        candidate.relative_to(root_real)
    except ValueError as exc:
        raise PathEscapeError(f"path escapes root: {rel!r}") from exc
    return candidate


def has_hidden_component(target: Path, root: Path) -> bool:
    """Return True if any component of ``target`` relative to ``root`` starts with a dot.

    ``target`` is expected to already be inside ``root`` (post-safe_resolve).
    Uses resolve() to normalize both before comparing.
    """
    root_real = root.resolve(strict=False)
    target_real = target.resolve(strict=False)
    try:
        rel = target_real.relative_to(root_real)
    except ValueError:
        return False
    return any(part.startswith(".") for part in rel.parts)
