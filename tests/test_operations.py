"""Unit tests for filemanaty.operations (filesystem primitives)."""
from __future__ import annotations

from pathlib import Path

import pytest

from filemanaty import operations as ops


def test_is_descendant_true(tmp_path):
    parent = tmp_path / "a"
    child = tmp_path / "a" / "b" / "c"
    assert ops.is_descendant(child, parent) is True


def test_is_descendant_self_is_true(tmp_path):
    assert ops.is_descendant(tmp_path, tmp_path) is True


def test_is_descendant_false(tmp_path):
    assert ops.is_descendant(tmp_path / "x", tmp_path / "y") is False


def test_next_free_name_file(tmp_path):
    (tmp_path / "a.png").write_text("1")
    assert ops.next_free_name(tmp_path, "a.png", is_dir=False) == "a (2).png"


def test_next_free_name_skips_taken(tmp_path):
    (tmp_path / "a.png").write_text("1")
    (tmp_path / "a (2).png").write_text("2")
    assert ops.next_free_name(tmp_path, "a.png", is_dir=False) == "a (3).png"


def test_next_free_name_dir(tmp_path):
    (tmp_path / "folder").mkdir()
    assert ops.next_free_name(tmp_path, "folder", is_dir=True) == "folder (2)"


def test_resolve_collision_no_clash(tmp_path):
    target, status = ops.resolve_collision(tmp_path, "new.png", None, is_dir=False)
    assert status == "ok"
    assert target == tmp_path / "new.png"


def test_resolve_collision_conflict(tmp_path):
    (tmp_path / "x.png").write_text("1")
    target, status = ops.resolve_collision(tmp_path, "x.png", None, is_dir=False)
    assert status == "conflict"
    assert target is None


def test_resolve_collision_skip(tmp_path):
    (tmp_path / "x.png").write_text("1")
    target, status = ops.resolve_collision(tmp_path, "x.png", "skip", is_dir=False)
    assert status == "skip" and target is None


def test_resolve_collision_replace(tmp_path):
    (tmp_path / "x.png").write_text("1")
    target, status = ops.resolve_collision(tmp_path, "x.png", "replace", is_dir=False)
    assert status == "replace" and target == tmp_path / "x.png"


def test_resolve_collision_keep_both(tmp_path):
    (tmp_path / "x.png").write_text("1")
    target, status = ops.resolve_collision(tmp_path, "x.png", "keep_both", is_dir=False)
    assert status == "ok" and target == tmp_path / "x (2).png"


def test_next_free_name_no_extension(tmp_path):
    (tmp_path / "Makefile").write_text("x")
    assert ops.next_free_name(tmp_path, "Makefile", is_dir=False) == "Makefile (2)"


def test_next_free_name_dotfile(tmp_path):
    (tmp_path / ".gitignore").write_text("x")
    # leading-dot name has no suffix per Path.suffix, so the whole name is the stem
    assert ops.next_free_name(tmp_path, ".gitignore", is_dir=False) == ".gitignore (2)"


def test_resolve_collision_unknown_policy_raises(tmp_path):
    (tmp_path / "x.png").write_text("1")
    with pytest.raises(ValueError):
        ops.resolve_collision(tmp_path, "x.png", "bogus", is_dir=False)


def test_make_dir_creates(tmp_path):
    out = ops.make_dir(tmp_path, "newdir", exist_ok=False)
    assert out == tmp_path / "newdir"
    assert out.is_dir()


def test_rename_file(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("hi")
    out = ops.rename(src, tmp_path / "new.txt", replace=False)
    assert out == tmp_path / "new.txt"
    assert out.read_text() == "hi"
    assert not src.exists()


def test_copy_one_file(tmp_path):
    src = tmp_path / "a.txt"; src.write_text("data")
    dst = tmp_path / "dst"; dst.mkdir()
    ops.copy_one(src, dst / "a.txt", replace=False)
    assert (dst / "a.txt").read_text() == "data"
    assert src.exists()  # copy leaves source


def test_copy_one_dir(tmp_path):
    src = tmp_path / "d"; src.mkdir(); (src / "f.txt").write_text("x")
    dst = tmp_path / "dst"; dst.mkdir()
    ops.copy_one(src, dst / "d", replace=False)
    assert (dst / "d" / "f.txt").read_text() == "x"


def test_copy_one_replace_dir(tmp_path):
    src = tmp_path / "s"; src.mkdir(); (src / "new.txt").write_text("new")
    dst = tmp_path / "d"; dst.mkdir()
    target = dst / "s"; target.mkdir(); (target / "old.txt").write_text("old")
    ops.copy_one(src, target, replace=True)
    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()  # replaced wholesale, not merged


def test_move_one_file(tmp_path):
    src = tmp_path / "a.txt"; src.write_text("data")
    dst = tmp_path / "dst"; dst.mkdir()
    ops.move_one(src, dst / "a.txt", replace=False)
    assert (dst / "a.txt").read_text() == "data"
    assert not src.exists()  # move removes source


def test_move_one_replace_dir(tmp_path):
    src = tmp_path / "s"; src.mkdir(); (src / "new.txt").write_text("new")
    dst = tmp_path / "d"; dst.mkdir()
    target = dst / "s"; target.mkdir(); (target / "old.txt").write_text("old")
    ops.move_one(src, target, replace=True)
    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()  # replaced wholesale
    assert not src.exists()                    # source moved away


def test_copy_one_replace_file(tmp_path):
    src = tmp_path / "a.txt"; src.write_text("new")
    target = tmp_path / "b.txt"; target.write_text("old")
    ops.copy_one(src, target, replace=True)
    assert target.read_text() == "new"
    assert src.exists()  # copy keeps source


def test_move_one_replace_file(tmp_path):
    src = tmp_path / "a.txt"; src.write_text("new")
    target = tmp_path / "b.txt"; target.write_text("old")
    ops.move_one(src, target, replace=True)
    assert target.read_text() == "new"
    assert not src.exists()  # move removes source


def test_move_to_trash_round_trip(tmp_path):
    item = tmp_path / "doomed.txt"; item.write_text("bye")
    tid = ops.move_to_trash(tmp_path, item)
    assert not item.exists()
    trash = tmp_path / ops.TRASH_DIRNAME
    assert (trash / f"{tid}.meta.json").is_file()
    meta = ops.trash_meta(tmp_path, tid)
    assert meta["original_rel_path"] == "doomed.txt"
    assert meta["original_name"] == "doomed.txt"
    assert ops.trash_item_path(tmp_path, tid).read_text() == "bye"


def test_list_trash_empty(tmp_path):
    assert ops.list_trash(tmp_path) == []


def test_list_trash_after_delete(tmp_path):
    item = tmp_path / "a.txt"; item.write_text("x")
    ops.move_to_trash(tmp_path, item)
    entries = ops.list_trash(tmp_path)
    assert len(entries) == 1
    assert entries[0]["original_name"] == "a.txt"


def test_list_trash_tolerates_missing_meta(tmp_path):
    item = tmp_path / "a.txt"; item.write_text("x")
    tid = ops.move_to_trash(tmp_path, item)
    # simulate the best-effort meta write having failed
    (tmp_path / ops.TRASH_DIRNAME / f"{tid}.meta.json").unlink()
    entries = ops.list_trash(tmp_path)
    assert len(entries) == 1
    assert entries[0]["original_name"] == "a.txt"
    assert entries[0]["id"] == tid


def test_list_trash_skips_empty_id_dir(tmp_path):
    trash = tmp_path / ops.TRASH_DIRNAME; trash.mkdir()
    (trash / "20260101-000000-deadbeef").mkdir()  # empty orphan id dir
    assert ops.list_trash(tmp_path) == []


def test_restore_round_trip(tmp_path):
    (tmp_path / "sub").mkdir()
    item = tmp_path / "sub" / "a.txt"; item.write_text("x")
    tid = ops.move_to_trash(tmp_path, item)
    assert not item.exists()
    ops.restore_from_trash(tmp_path, tid, item, replace=False)
    assert item.read_text() == "x"
    assert ops.list_trash(tmp_path) == []   # trash entry consumed


def test_purge_one(tmp_path):
    item = tmp_path / "a.txt"; item.write_text("x")
    tid = ops.move_to_trash(tmp_path, item)
    ops.purge(tmp_path, tid)
    assert ops.list_trash(tmp_path) == []
