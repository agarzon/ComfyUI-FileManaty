"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """A temp directory usable as a 'root' for security/api tests.

    Populated with a small fixture tree:
        <root>/
            top.txt
            sub/
                nested.txt
                inner/
                    deep.txt
    """
    (tmp_path / "top.txt").write_text("top-level file")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("nested file")
    (tmp_path / "sub" / "inner").mkdir()
    (tmp_path / "sub" / "inner" / "deep.txt").write_text("deep file")
    return tmp_path


@pytest.fixture
def outside_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory OUTSIDE any test root, used to test escape attempts."""
    p = tmp_path_factory.mktemp("outside")
    (p / "secret.txt").write_text("nothing to see")
    return p
