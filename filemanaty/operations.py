"""Filesystem write operations for ComfyUI-FileManaty.

Every function takes ALREADY-RESOLVED Paths (validated by
security.safe_resolve / safe_name in api.py). Functions never accept raw
user paths. All are synchronous; api.py runs them via run_in_executor.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Optional

TRASH_DIRNAME = ".filemanaty_trash"


def is_descendant(child: Path, parent: Path) -> bool:
    """True if ``child`` equals ``parent`` or lives inside it (after resolve)."""
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def next_free_name(dst_dir: Path, name: str, *, is_dir: bool) -> str:
    """First ``name (N)`` (N>=2) variant that does not exist in ``dst_dir``."""
    if is_dir:
        stem, suffix = name, ""
    else:
        suffix = Path(name).suffix
        stem = name[: len(name) - len(suffix)] if suffix else name
    i = 2
    while True:
        candidate = f"{stem} ({i}){suffix}"
        if not (dst_dir / candidate).exists():
            return candidate
        i += 1


def resolve_collision(
    dst_dir: Path, name: str, on_conflict: Optional[str], *, is_dir: bool
) -> tuple[Optional[Path], str]:
    """Decide the destination for ``name`` in ``dst_dir``.

    on_conflict:
      None        -> (None, "conflict") if the target exists, else (target, "ok")
      "skip"      -> (None, "skip")
      "replace"   -> (target, "replace")
      "keep_both" -> (dst_dir / next_free_name(...), "ok")
    Unknown values raise ValueError.

    Returns (target_path_or_None, status); status is one of
    "ok", "conflict", "skip", "replace".
    """
    target = dst_dir / name
    if not target.exists():
        return target, "ok"
    if on_conflict is None:
        return None, "conflict"
    if on_conflict == "skip":
        return None, "skip"
    if on_conflict == "replace":
        return target, "replace"
    if on_conflict == "keep_both":
        return dst_dir / next_free_name(dst_dir, name, is_dir=is_dir), "ok"
    raise ValueError(f"unknown on_conflict: {on_conflict!r}")


def make_dir(parent: Path, name: str, *, exist_ok: bool) -> Path:
    """Create directory ``name`` inside ``parent``. ``exist_ok`` tolerates an
    already-existing directory (caller resolves conflicts beforehand)."""
    target = parent / name
    target.mkdir(exist_ok=exist_ok)
    return target


def _overwrite_clear(target: Path) -> None:
    """Remove an existing target so a move/copy can replace it."""
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


def rename(src: Path, target: Path, *, replace: bool) -> Path:
    """Rename ``src`` to ``target`` (same or different parent)."""
    if replace and target.exists() and src != target:
        _overwrite_clear(target)
    os.replace(src, target)
    return target


def _stage_and_swap(transfer_fn, src: Path, target: Path) -> None:
    """Stage ``src`` into a hidden temp sibling of ``target`` via ``transfer_fn``
    (which performs the actual copy/move into the temp path), then atomically
    swap it over the existing target. Keeps the old target intact until the new
    content is fully staged.

    NB: a crash between _overwrite_clear and os.replace can orphan the temp
    (.fmtmp-*) entry — an inherent non-transactional-FS limitation. For move,
    the staged data lives in the temp entry, so it is recoverable by hand.
    """
    tmp = target.parent / f".fmtmp-{secrets.token_hex(4)}"
    try:
        transfer_fn(src, tmp)
    except OSError:
        if tmp.is_dir() and not tmp.is_symlink():
            shutil.rmtree(tmp, ignore_errors=True)
        elif tmp.exists():
            tmp.unlink()
        raise
    _overwrite_clear(target)
    os.replace(tmp, target)


def _copy_into(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def copy_one(src: Path, target: Path, *, replace: bool) -> None:
    """Copy ``src`` to ``target`` (file or directory tree).

    When replacing an existing target, copy into a temp sibling first and
    atomically swap, so a mid-copy failure never destroys the existing target.
    """
    if not (replace and target.exists()) or src == target:
        _copy_into(src, target)
        return
    _stage_and_swap(_copy_into, src, target)


def move_one(src: Path, target: Path, *, replace: bool) -> None:
    """Move ``src`` to ``target`` (file or directory tree).

    When replacing an existing target, stage into a temp sibling first and
    atomically swap, so the existing target survives until the new content is
    fully in place.
    """
    if not (replace and target.exists()) or src == target:
        shutil.move(str(src), str(target))
        return
    _stage_and_swap(lambda s, d: shutil.move(str(s), str(d)), src, target)


# ---------------------------------------------------------------------------
# Trash primitives
# ---------------------------------------------------------------------------

def _trash_dir(root: Path) -> Path:
    return root / TRASH_DIRNAME


def _new_trash_id() -> str:
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{secrets.token_hex(4)}"


def _entry_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def move_to_trash(root: Path, item: Path) -> str:
    """Move ``item`` into ``root``'s trash. Returns the trash id."""
    rel = item.resolve().relative_to(root.resolve()).as_posix()
    trash = _trash_dir(root)
    trash.mkdir(exist_ok=True)
    tid = _new_trash_id()
    iddir = trash / tid
    iddir.mkdir()
    size = _entry_size(item)  # measured before the move
    try:
        shutil.move(str(item), str(iddir / item.name))
    except OSError:
        # nothing moved — remove the empty id dir so no orphan is left
        shutil.rmtree(iddir, ignore_errors=True)
        raise
    # Item is now safely in the trash. Meta is best-effort: if it can't be
    # written, the data is still recoverable and list_trash (next task)
    # synthesizes a fallback entry for a meta-less id dir.
    meta = {
        "id": tid,
        "original_rel_path": rel,
        "original_name": item.name,
        "deleted_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "size": size,
    }
    try:
        (trash / f"{tid}.meta.json").write_text(json.dumps(meta))
    except OSError:
        pass
    return tid


def list_trash(root: Path) -> list[dict]:
    """List trashed items for ``root``. Tolerates id dirs whose meta file is
    missing or corrupt (synthesizes a minimal entry); skips empty id dirs."""
    trash = _trash_dir(root)
    if not trash.is_dir():
        return []
    out: list[dict] = []
    for iddir in sorted(p for p in trash.iterdir() if p.is_dir()):
        tid = iddir.name
        entries = [e for e in iddir.iterdir()]
        if not entries:
            continue  # empty / orphan id dir — nothing to restore
        meta_file = trash / f"{tid}.meta.json"
        if meta_file.exists():
            try:
                out.append(json.loads(meta_file.read_text()))
                continue
            except (OSError, json.JSONDecodeError):
                pass
        # fallback for a meta-less or corrupt-meta id dir
        item = entries[0]
        out.append({
            "id": tid,
            "original_rel_path": item.name,
            "original_name": item.name,
            "deleted_at": None,
            "size": _entry_size(item),
        })
    return out


def restore_from_trash(root: Path, tid: str, target: Path, *, replace: bool) -> None:
    """Move the stored item for ``tid`` back to ``target`` and drop its meta."""
    stored = trash_item_path(root, tid)
    target.parent.mkdir(parents=True, exist_ok=True)
    move_one(stored, target, replace=replace)   # data-safe (temp-swap on replace)
    iddir = _trash_dir(root) / tid
    shutil.rmtree(iddir, ignore_errors=True)
    meta = _trash_dir(root) / f"{tid}.meta.json"
    if meta.exists():
        meta.unlink()


def purge(root: Path, tid: str) -> None:
    iddir = _trash_dir(root) / tid
    meta = _trash_dir(root) / f"{tid}.meta.json"
    shutil.rmtree(iddir, ignore_errors=True)
    if meta.exists():
        meta.unlink()


def purge_all(root: Path) -> None:
    trash = _trash_dir(root)
    if trash.is_dir():
        shutil.rmtree(trash, ignore_errors=True)


def delete_permanent(item: Path) -> None:
    if item.is_dir() and not item.is_symlink():
        shutil.rmtree(item)
    else:
        item.unlink()


def trash_meta(root: Path, tid: str) -> dict:
    return json.loads((_trash_dir(root) / f"{tid}.meta.json").read_text())


def trash_item_path(root: Path, tid: str) -> Path:
    """The stored file/folder inside its trash id dir."""
    iddir = _trash_dir(root) / tid
    entries = [p for p in iddir.iterdir()]
    if not entries:
        raise FileNotFoundError(tid)
    return entries[0]
