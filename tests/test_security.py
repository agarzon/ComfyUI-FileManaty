"""Adversarial path-safety tests.

This is the most security-critical test file in the project. Add
positive AND negative cases for every new attack vector.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from filemanaty.security import safe_resolve, PathEscapeError


def test_empty_path_returns_root(tmp_root):
    assert safe_resolve(tmp_root, "") == tmp_root.resolve()


def test_simple_relative_path(tmp_root):
    assert safe_resolve(tmp_root, "top.txt") == (tmp_root / "top.txt").resolve()


def test_nested_relative_path(tmp_root):
    assert safe_resolve(tmp_root, "sub/inner/deep.txt") == (tmp_root / "sub/inner/deep.txt").resolve()


def test_path_with_trailing_slash(tmp_root):
    assert safe_resolve(tmp_root, "sub/") == (tmp_root / "sub").resolve()


def test_path_with_leading_dot_slash(tmp_root):
    # ./sub is fine — resolves to sub
    assert safe_resolve(tmp_root, "./sub") == (tmp_root / "sub").resolve()


def test_unicode_filename(tmp_root):
    name = "café 🎨.txt"
    (tmp_root / name).write_text("x")
    assert safe_resolve(tmp_root, name) == (tmp_root / name).resolve()


@pytest.mark.parametrize("bad", [
    "/etc/passwd",
    "/",
    "/absolute/anywhere",
    "\\Windows\\System32",
    "\\\\?\\C:\\Windows",
    "\\\\server\\share\\file",
    "C:\\Windows",
    "c:/Windows",
    "D:foo",
])
def test_absolute_paths_rejected(tmp_root, bad):
    with pytest.raises(PathEscapeError):
        safe_resolve(tmp_root, bad)


@pytest.mark.parametrize("bad", [
    "file\x00.png",
    "\x00",
    "ok/\x00/escape",
])
def test_null_byte_rejected(tmp_root, bad):
    with pytest.raises(PathEscapeError):
        safe_resolve(tmp_root, bad)


def test_none_rejected(tmp_root):
    with pytest.raises(PathEscapeError):
        safe_resolve(tmp_root, None)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [
    "..",
    "../",
    "../outside.txt",
    "../../etc/passwd",
    "sub/../../escape",
    "sub/../../../etc",
    "sub/inner/../../../../escape",
    "./../escape",
    "%2e%2e/escape",          # client must URL-decode; we still reject literal '%2e' as a name
])
def test_traversal_rejected(tmp_root, bad):
    if "%2e%2e" in bad:
        # %2e is just a filename to us; rejected only if the resolved
        # path escapes the root. URL-decoding happens at the HTTP layer.
        # Here we expect it to NOT raise (it's a valid relative name).
        # This documents that the HTTP layer must decode before calling.
        safe_resolve(tmp_root, bad)
    else:
        with pytest.raises(PathEscapeError):
            safe_resolve(tmp_root, bad)


@pytest.mark.skipif(sys.platform != "win32", reason="backslash is a literal char on Linux")
def test_mixed_slashes_traversal_rejected(tmp_root):
    with pytest.raises(PathEscapeError):
        safe_resolve(tmp_root, "sub\\..\\..\\escape")


def test_symlink_inside_root_pointing_outside_is_rejected(tmp_root, outside_dir):
    # Create a symlink inside the root that points OUT of the root.
    link = tmp_root / "escape_link"
    os.symlink(outside_dir, link, target_is_directory=True)

    with pytest.raises(PathEscapeError):
        safe_resolve(tmp_root, "escape_link/secret.txt")


def test_symlink_inside_root_pointing_inside_is_allowed(tmp_root):
    # Symlink inside the root pointing to another file inside the root.
    target = tmp_root / "sub" / "nested.txt"
    link = tmp_root / "inside_link"
    os.symlink(target, link)

    assert safe_resolve(tmp_root, "inside_link").is_relative_to(tmp_root.resolve())


def test_symlinked_root_is_resolved_consistently(tmp_path, outside_dir):
    # Root itself is reached via a symlink — resolve must still recognize
    # files inside it as in-root.
    (outside_dir / "x.txt").write_text("hi")
    link_root = tmp_path / "root_link"
    os.symlink(outside_dir, link_root, target_is_directory=True)

    assert safe_resolve(link_root, "x.txt") == (outside_dir / "x.txt").resolve()
