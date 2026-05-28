"""Integration tests for the HTTP API.

We mount the routes on a fresh aiohttp.web.Application — no PromptServer
required — so this works in plain pytest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from PIL import Image

from filemanaty import api as api_module
from filemanaty.config import Config, FilesConfig, RootConfig, ThumbnailsConfig

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_factory(aiohttp_client, tmp_root, tmp_path_factory, monkeypatch):
    def _factory(*, files=None, thumbs=None):
        cfg = Config(
            roots=(RootConfig(id="t", label="T", path=tmp_root.resolve()),),
            files=files or FilesConfig(),
            thumbnails=thumbs or ThumbnailsConfig(),
        )
        monkeypatch.setattr(api_module, "_get_config", lambda: cfg)
        monkeypatch.setenv("FILEMANATY_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
        app = web.Application()
        api_module.attach_routes(app)
        return aiohttp_client(app)
    return _factory


async def test_roots_endpoint(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/roots")
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["data"]["roots"] == [{"id": "t", "label": "T"}]


async def test_list_root_returns_top_level(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=")
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    names = sorted(e["name"] for e in body["data"]["entries"])
    assert names == ["sub", "top.txt"]


async def test_list_subfolder(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=sub")
    body = await resp.json()
    names = sorted(e["name"] for e in body["data"]["entries"])
    assert names == ["inner", "nested.txt"]
    assert body["data"]["parent"] == ""


async def test_list_unknown_root_returns_403(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=nope&path=")
    assert resp.status == 403
    body = await resp.json()
    assert body["error"]["code"] == "ACCESS_DENIED"


async def test_list_escape_attempt_returns_403(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=../../etc")
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "ACCESS_DENIED"


async def test_list_missing_root_param_returns_400(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list")
    assert resp.status == 400
    assert (await resp.json())["error"]["code"] == "BAD_REQUEST"


async def test_list_root_parent_is_null(client_factory):
    """The root listing has parent=null, not empty string."""
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=")
    body = await resp.json()
    assert body["data"]["parent"] is None


async def test_list_deep_parent_is_dirname(client_factory, tmp_root):
    """Listing sub/inner should report parent='sub'."""
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=sub/inner")
    body = await resp.json()
    assert body["data"]["parent"] == "sub"


async def test_list_not_found_returns_404(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=ghost-folder")
    assert resp.status == 404
    assert (await resp.json())["error"]["code"] == "NOT_FOUND"


async def test_list_file_path_returns_400(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=top.txt")
    assert resp.status == 400
    assert (await resp.json())["error"]["code"] == "BAD_REQUEST"


async def test_list_excludes_hidden_by_default(client_factory, tmp_root):
    (tmp_root / ".hidden").write_text("invisible")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await resp.json())["data"]["entries"]]
    assert ".hidden" not in names


async def test_list_includes_hidden_when_configured(client_factory, tmp_root):
    (tmp_root / ".hidden").write_text("visible")
    client = await client_factory(files=FilesConfig(allow_hidden=True))
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await resp.json())["data"]["entries"]]
    assert ".hidden" in names


def _make_image(path: Path, size=(800, 600)):
    img = Image.new("RGB", size, (10, 200, 30))
    img.save(path, format="PNG")


async def test_thumbnail_returns_webp(client_factory, tmp_root):
    _make_image(tmp_root / "pic.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=pic.png")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/webp"
    body = await resp.read()
    # WebP signature: RIFF????WEBP
    assert body[:4] == b"RIFF" and body[8:12] == b"WEBP"


async def test_thumbnail_unsupported_extension_returns_404(client_factory, tmp_root):
    (tmp_root / "doc.txt").write_text("hi")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=doc.txt")
    assert resp.status == 404
    assert (await resp.json())["error"]["code"] == "THUMB_UNSUPPORTED"


async def test_thumbnail_escape_returns_403(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=../etc")
    assert resp.status == 403


async def test_thumbnail_cache_hit_returns_same_bytes(client_factory, tmp_root):
    """A second request for the same file returns the cached thumbnail."""
    _make_image(tmp_root / "pic.png")
    client = await client_factory()
    first = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=pic.png")
    body1 = await first.read()
    second = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=pic.png")
    body2 = await second.read()
    assert body1 == body2
    assert first.status == second.status == 200


async def test_thumbnail_corrupt_image_returns_404(client_factory, tmp_root):
    """A file with a valid extension but corrupt content returns THUMB_UNSUPPORTED."""
    (tmp_root / "corrupt.png").write_bytes(b"this is not a PNG")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=corrupt.png")
    assert resp.status == 404
    assert (await resp.json())["error"]["code"] == "THUMB_UNSUPPORTED"


async def test_preview_streams_original_png(client_factory, tmp_root):
    _make_image(tmp_root / "pic.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/preview?root=t&path=pic.png")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("image/png")
    body = await resp.read()
    assert body[:8] == b"\x89PNG\r\n\x1a\n"


async def test_download_sets_attachment_header(client_factory, tmp_root):
    _make_image(tmp_root / "pic.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/download?root=t&path=pic.png")
    assert resp.status == 200
    cd = resp.headers["Content-Disposition"]
    assert cd.startswith("attachment;")
    assert "pic.png" in cd


async def test_preview_escape_returns_403(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/preview?root=t&path=../etc")
    assert resp.status == 403


async def test_preview_missing_returns_404(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/preview?root=t&path=ghost.png")
    assert resp.status == 404


async def test_preview_hidden_file_returns_403(client_factory, tmp_root):
    """allow_hidden=False (default) must block previewing hidden files."""
    _make_image(tmp_root / ".hidden.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/preview?root=t&path=.hidden.png")
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "ACCESS_DENIED"


async def test_download_hidden_file_returns_403(client_factory, tmp_root):
    _make_image(tmp_root / ".hidden.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/download?root=t&path=.hidden.png")
    assert resp.status == 403


async def test_thumbnail_hidden_file_returns_403(client_factory, tmp_root):
    _make_image(tmp_root / ".hidden.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=.hidden.png")
    assert resp.status == 403


async def test_preview_html_file_returns_404_unsupported(client_factory, tmp_root):
    """Critical XSS defense: /preview must refuse non-image extensions."""
    (tmp_root / "shell.html").write_text("<script>alert(1)</script>")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/preview?root=t&path=shell.html")
    assert resp.status == 404
    assert (await resp.json())["error"]["code"] == "PREVIEW_UNSUPPORTED"


async def test_download_non_image_works(client_factory, tmp_root):
    """/download is not restricted to image extensions."""
    (tmp_root / "data.json").write_text('{"ok": true}')
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/download?root=t&path=data.json")
    assert resp.status == 200
    assert resp.headers["Content-Disposition"].startswith("attachment;")
    assert "X-Content-Type-Options" in resp.headers


async def test_download_unicode_filename(client_factory, tmp_root):
    """Content-Disposition filename* must encode non-ASCII correctly."""
    name = "café_🎨.png"
    _make_image(tmp_root / name)
    client = await client_factory()
    # URL-encode the filename in the query string
    from urllib.parse import quote
    resp = await client.get(f"/filemanaty/api/v1/download?root=t&path={quote(name)}")
    assert resp.status == 200
    cd = resp.headers["Content-Disposition"]
    assert "filename*=UTF-8''" in cd
    # The percent-encoded UTF-8 form of "café" includes %C3%A9; verify presence
    assert "%C3%A9" in cd


async def test_list_hidden_directory_returns_403(client_factory, tmp_root):
    """A directory whose name starts with '.' should not be listable."""
    (tmp_root / ".secret_dir").mkdir()
    (tmp_root / ".secret_dir" / "file.txt").write_text("hidden")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=.secret_dir")
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "ACCESS_DENIED"


async def test_file_inside_hidden_dir_blocked_on_download(client_factory, tmp_root):
    """A non-hidden file inside a hidden directory should still be 403."""
    (tmp_root / ".secret_dir").mkdir()
    _make_image(tmp_root / ".secret_dir" / "inside.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/download?root=t&path=.secret_dir/inside.png")
    assert resp.status == 403


async def test_file_inside_hidden_dir_blocked_on_preview(client_factory, tmp_root):
    (tmp_root / ".secret_dir").mkdir()
    _make_image(tmp_root / ".secret_dir" / "inside.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/preview?root=t&path=.secret_dir/inside.png")
    assert resp.status == 403


async def test_file_inside_hidden_dir_blocked_on_thumbnail(client_factory, tmp_root):
    (tmp_root / ".secret_dir").mkdir()
    _make_image(tmp_root / ".secret_dir" / "inside.png")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/thumbnail?root=t&path=.secret_dir/inside.png")
    assert resp.status == 403


async def test_list_hidden_dir_allowed_when_configured(client_factory, tmp_root):
    """When allow_hidden=True, hidden directories ARE listable."""
    (tmp_root / ".secret_dir").mkdir()
    (tmp_root / ".secret_dir" / "file.txt").write_text("ok")
    client = await client_factory(files=FilesConfig(allow_hidden=True))
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=.secret_dir")
    assert resp.status == 200
