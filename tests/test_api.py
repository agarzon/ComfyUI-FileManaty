"""Integration tests for the HTTP API.

We mount the routes on a fresh aiohttp.web.Application — no PromptServer
required — so this works in plain pytest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import FormData, web
from PIL import Image

from filemanaty import api as api_module
from filemanaty.config import Config, FilesConfig, RootConfig, ThumbnailsConfig, WriteConfig

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_factory(aiohttp_client, tmp_root, tmp_path_factory, monkeypatch):
    def _factory(*, files=None, thumbs=None, write=None):
        cfg = Config(
            roots=(RootConfig(id="t", label="T", path=tmp_root.resolve()),),
            files=files or FilesConfig(),
            thumbnails=thumbs or ThumbnailsConfig(),
            write=write or WriteConfig(),
        )
        monkeypatch.setattr(api_module, "_get_config", lambda: cfg)
        monkeypatch.setenv("FILEMANATY_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
        app = web.Application()
        api_module.attach_routes(app)
        return aiohttp_client(app)
    return _factory


@pytest.fixture
def two_root_client(aiohttp_client, tmp_root, tmp_root2, tmp_path_factory, monkeypatch):
    async def _make():
        cfg = Config(
            roots=(
                RootConfig(id="t", label="T", path=tmp_root.resolve()),
                RootConfig(id="u", label="U", path=tmp_root2.resolve()),
            ),
            files=FilesConfig(),
            thumbnails=ThumbnailsConfig(),
        )
        monkeypatch.setattr(api_module, "_get_config", lambda: cfg)
        monkeypatch.setenv("FILEMANATY_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
        app = web.Application()
        api_module.attach_routes(app)
        return await aiohttp_client(app)
    return _make


@pytest.fixture
def ro_rw_client(aiohttp_client, tmp_root, tmp_root2, tmp_path_factory, monkeypatch):
    """Two roots: 'ro' is read-only, 'rw' is writable. For read-only enforcement."""
    async def _make():
        cfg = Config(
            roots=(
                RootConfig(id="ro", label="RO", path=tmp_root.resolve(), writable=False),
                RootConfig(id="rw", label="RW", path=tmp_root2.resolve(), writable=True),
            ),
            files=FilesConfig(),
            thumbnails=ThumbnailsConfig(),
        )
        monkeypatch.setattr(api_module, "_get_config", lambda: cfg)
        monkeypatch.setenv("FILEMANATY_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
        app = web.Application()
        api_module.attach_routes(app)
        return await aiohttp_client(app)
    return _make


async def test_roots_endpoint(client_factory):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/roots")
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["data"]["roots"] == [{"id": "t", "label": "T", "writable": True}]


async def test_roots_endpoint_exposes_read_only(ro_rw_client):
    client = await ro_rw_client()
    resp = await client.get("/filemanaty/api/v1/roots")
    by_id = {r["id"]: r for r in (await resp.json())["data"]["roots"]}
    assert by_id["ro"]["writable"] is False
    assert by_id["rw"]["writable"] is True


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


async def test_list_include_hidden_true_surfaces_dotfiles(client_factory, tmp_root):
    (tmp_root / ".hidden").write_text("visible-via-query-param")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=&include_hidden=true")
    assert resp.status == 200
    names = [e["name"] for e in (await resp.json())["data"]["entries"]]
    assert ".hidden" in names


async def test_list_include_hidden_false_hides_dotfiles(client_factory, tmp_root):
    (tmp_root / ".hidden").write_text("hidden")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=&include_hidden=false")
    names = [e["name"] for e in (await resp.json())["data"]["entries"]]
    assert ".hidden" not in names


async def test_list_include_hidden_accepts_aliases(client_factory, tmp_root):
    (tmp_root / ".hidden").write_text("hi")
    client = await client_factory()
    for alias in ("1", "true", "TRUE", "True"):
        resp = await client.get(f"/filemanaty/api/v1/list?root=t&path=&include_hidden={alias}")
        assert resp.status == 200, alias
        names = [e["name"] for e in (await resp.json())["data"]["entries"]]
        assert ".hidden" in names, alias
    for alias in ("0", "false", "FALSE", "False"):
        resp = await client.get(f"/filemanaty/api/v1/list?root=t&path=&include_hidden={alias}")
        assert resp.status == 200, alias
        names = [e["name"] for e in (await resp.json())["data"]["entries"]]
        assert ".hidden" not in names, alias


async def test_list_include_hidden_invalid_returns_400(client_factory, tmp_root):
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=&include_hidden=banana")
    assert resp.status == 400
    assert (await resp.json())["error"]["code"] == "BAD_REQUEST"


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
    """When include_hidden=true, hidden directories ARE listable."""
    (tmp_root / ".secret_dir").mkdir()
    (tmp_root / ".secret_dir" / "file.txt").write_text("ok")
    client = await client_factory()
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=.secret_dir&include_hidden=true")
    assert resp.status == 200


async def _post(client, path, payload):
    return await client.post(path, json=payload)


async def test_mkdir_creates_folder(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "", "name": "fresh"})
    assert resp.status == 200
    assert (await resp.json())["ok"] is True


async def test_mkdir_rejects_traversal_name(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "", "name": "../escape"})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "ACCESS_DENIED"


async def test_mkdir_conflict_returns_409(client_factory):
    client = await client_factory()
    # 'sub' already exists in tmp_root fixture
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "", "name": "sub"})
    assert resp.status == 409
    body = await resp.json()
    assert body["error"]["code"] == "CONFLICT"
    assert "sub" in body["error"]["conflicts"]


async def test_mkdir_invalid_on_conflict_returns_400(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "", "name": "sub", "on_conflict": "bogus"})
    assert resp.status == 400
    assert (await resp.json())["error"]["code"] == "BAD_REQUEST"


async def test_mkdir_parent_is_file_returns_400(client_factory):
    client = await client_factory()
    # top.txt is a file in tmp_root, not a directory
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "top.txt", "name": "x"})
    assert resp.status == 400
    assert (await resp.json())["error"]["code"] == "BAD_REQUEST"


async def test_mkdir_keep_both_on_existing(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "", "name": "sub", "on_conflict": "keep_both"})
    assert resp.status == 200
    assert (await resp.json())["data"]["name"] == "sub (2)"


async def test_rename_file(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "renamed.txt"})
    assert resp.status == 200
    assert (await resp.json())["data"]["name"] == "renamed.txt"


async def test_rename_rejects_separator_in_name(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "a/b.txt"})
    assert resp.status == 403


async def test_rename_conflict_returns_409(client_factory):
    client = await client_factory()
    # rename top.txt -> sub (a name that already exists)
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "sub"})
    assert resp.status == 409
    assert (await resp.json())["error"]["code"] == "CONFLICT"


async def test_rename_invalid_on_conflict_returns_400(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "sub", "on_conflict": "bogus"})
    assert resp.status == 400
    assert (await resp.json())["error"]["code"] == "BAD_REQUEST"


async def test_rename_same_name_replace_is_safe(client_factory):
    # Renaming a file to its OWN name with replace must NOT destroy it.
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "top.txt", "on_conflict": "replace"})
    assert resp.status == 200
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "top.txt" in names


async def test_rename_replace_overwrites(client_factory):
    client = await client_factory()
    # rename file top.txt onto existing dir 'sub' with replace -> sub becomes the file
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "sub", "on_conflict": "replace"})
    assert resp.status == 200
    assert (await resp.json())["data"]["name"] == "sub"


async def test_rename_keep_both(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": "sub", "on_conflict": "keep_both"})
    assert resp.status == 200
    assert (await resp.json())["data"]["name"] == "sub (2)"


async def test_rename_directory(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "sub", "name": "renamed_sub"})
    assert resp.status == 200
    assert (await resp.json())["data"]["name"] == "renamed_sub"


async def test_rename_missing_src_404(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "nope.txt", "name": "x.txt"})
    assert resp.status == 404


async def test_rename_root_rejected(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "", "name": "x"})
    assert resp.status == 403


async def test_copy_cross_root(two_root_client):
    client = await two_root_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "u", "dst_path": ""})
    assert resp.status == 200
    body = await resp.json()
    assert body["data"]["results"][0]["status"] == "done"
    listing = await client.get("/filemanaty/api/v1/list?root=u&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "top.txt" in names


async def test_copy_conflict_returns_409(two_root_client):
    client = await two_root_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "u", "src_items": ["existing.txt"], "dst_root": "u", "dst_path": ""})
    assert resp.status == 409
    assert "existing.txt" in (await resp.json())["error"]["conflicts"]


async def test_copy_keep_both(two_root_client):
    client = await two_root_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "u", "src_items": ["existing.txt"], "dst_root": "u",
        "dst_path": "", "on_conflict": "keep_both"})
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["name"] == "existing (2).txt"
    listing = await client.get("/filemanaty/api/v1/list?root=u&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "existing.txt" in names and "existing (2).txt" in names


async def test_copy_escape_src_returns_403(two_root_client):
    client = await two_root_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["../../etc/passwd"], "dst_root": "u", "dst_path": ""})
    assert resp.status == 403


async def test_copy_invalid_on_conflict_returns_400(two_root_client):
    client = await two_root_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "u", "dst_path": "",
        "on_conflict": "bogus"})
    assert resp.status == 400


async def test_copy_into_descendant_returns_400(client_factory):
    client = await client_factory()
    # copy 'sub' into 'sub/inner' (a descendant of itself)
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["sub"], "dst_root": "t", "dst_path": "sub/inner"})
    assert resp.status == 400


async def test_copy_dst_not_dir_returns_400(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["sub"], "dst_root": "t", "dst_path": "top.txt"})
    assert resp.status == 400


async def test_copy_duplicate_items_returns_409(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["top.txt", "top.txt"], "dst_root": "t", "dst_path": "sub"})
    assert resp.status == 409


async def test_copy_missing_src_returns_404(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["ghost.txt"], "dst_root": "t", "dst_path": "sub"})
    assert resp.status == 404


async def test_copy_root_as_src_returns_403(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": [""], "dst_root": "t", "dst_path": "sub"})
    assert resp.status == 403


async def test_move_cross_root(two_root_client):
    client = await two_root_client()
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "u", "dst_path": ""})
    assert resp.status == 200
    # gone from source listing
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "top.txt" not in names
    # present in destination
    dst_listing = await client.get("/filemanaty/api/v1/list?root=u&path=")
    dst_names = [e["name"] for e in (await dst_listing.json())["data"]["entries"]]
    assert "top.txt" in dst_names


async def test_move_folder_into_itself_rejected(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "t", "src_items": ["sub"], "dst_root": "t", "dst_path": "sub/inner"})
    assert resp.status == 400


async def test_move_replace_via_api(two_root_client):
    client = await two_root_client()
    # seed a collision: copy top.txt into u so u/top.txt exists
    await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "u", "dst_path": ""})
    # move t/top.txt onto u/top.txt with replace
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "u",
        "dst_path": "", "on_conflict": "replace"})
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["status"] == "done"
    src_listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    assert "top.txt" not in [e["name"] for e in (await src_listing.json())["data"]["entries"]]
    dst_listing = await client.get("/filemanaty/api/v1/list?root=u&path=")
    assert "top.txt" in [e["name"] for e in (await dst_listing.json())["data"]["entries"]]


async def test_move_missing_src_returns_404(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "t", "src_items": ["ghost.txt"], "dst_root": "t", "dst_path": "sub"})
    assert resp.status == 404


def ops_trash_dirname():
    from filemanaty import operations as o
    return o.TRASH_DIRNAME


async def test_delete_to_trash(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/delete",
                       {"root": "t", "items": ["top.txt"]})
    assert resp.status == 200
    body = (await resp.json())["data"]["results"][0]
    assert body["status"] == "trashed"
    assert body.get("id")
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "top.txt" not in names            # gone from listing
    assert ops_trash_dirname() not in names  # trash dir stays hidden


async def test_delete_permanent(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/delete",
                       {"root": "t", "items": ["top.txt"], "permanent": True})
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["status"] == "deleted"


async def test_delete_root_rejected(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/delete",
                       {"root": "t", "items": [""]})
    assert resp.status == 403


async def test_delete_missing_item_404(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/delete",
                       {"root": "t", "items": ["ghost.txt"]})
    assert resp.status == 404


async def test_delete_trash_dir_rejected(client_factory):
    client = await client_factory()
    # first create the trash dir by trashing something
    await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    # now attempt to delete the trash dir itself via /delete
    resp = await _post(client, "/filemanaty/api/v1/delete",
                       {"root": "t", "items": [ops_trash_dirname()]})
    assert resp.status == 403


async def test_trash_list_endpoint(client_factory):
    client = await client_factory()
    await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    resp = await client.get("/filemanaty/api/v1/trash/list?root=t")
    assert resp.status == 200
    items = (await resp.json())["data"]["items"]
    assert items[0]["original_name"] == "top.txt"


async def test_trash_restore_endpoint(client_factory):
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    resp = await _post(client, "/filemanaty/api/v1/trash/restore", {"root": "t", "ids": [tid]})
    assert resp.status == 200
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "top.txt" in names


async def test_trash_restore_conflict_returns_409(client_factory):
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    # recreate something at the original path so restore conflicts (a dir named top.txt)
    await _post(client, "/filemanaty/api/v1/mkdir", {"root": "t", "path": "", "name": "top.txt"})
    resp = await _post(client, "/filemanaty/api/v1/trash/restore", {"root": "t", "ids": [tid]})
    assert resp.status == 409


async def test_trash_restore_keep_both(client_factory):
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    await _post(client, "/filemanaty/api/v1/mkdir", {"root": "t", "path": "", "name": "top.txt"})
    resp = await _post(client, "/filemanaty/api/v1/trash/restore",
                       {"root": "t", "ids": [tid], "on_conflict": "keep_both"})
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["name"] == "top (2).txt"


async def test_trash_restore_duplicate_ids_ok(client_factory):
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    resp = await _post(client, "/filemanaty/api/v1/trash/restore",
                       {"root": "t", "ids": [tid, tid]})
    assert resp.status == 200
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    assert "top.txt" in [e["name"] for e in (await listing.json())["data"]["entries"]]


async def test_trash_restore_unknown_id_404(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/trash/restore",
                       {"root": "t", "ids": ["20990101-000000-deadbeef"]})
    assert resp.status == 404


async def test_trash_restore_invalid_on_conflict_400(client_factory):
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    resp = await _post(client, "/filemanaty/api/v1/trash/restore",
                       {"root": "t", "ids": [tid], "on_conflict": "bogus"})
    assert resp.status == 400


async def test_trash_purge_selected(client_factory):
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    resp = await _post(client, "/filemanaty/api/v1/trash/purge", {"root": "t", "ids": [tid]})
    assert resp.status == 200
    listing = await client.get("/filemanaty/api/v1/trash/list?root=t")
    assert (await listing.json())["data"]["items"] == []


async def test_trash_purge_all(client_factory):
    client = await client_factory()
    await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    resp = await _post(client, "/filemanaty/api/v1/trash/purge", {"root": "t", "all": True})
    assert resp.status == 200
    listing = await client.get("/filemanaty/api/v1/trash/list?root=t")
    assert (await listing.json())["data"]["items"] == []


async def test_trash_purge_rejects_traversal_id(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/trash/purge",
                       {"root": "t", "ids": ["../../etc"]})
    assert resp.status == 403


async def test_trash_purge_missing_ids_and_all_returns_400(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/trash/purge", {"root": "t"})
    assert resp.status == 400


async def test_upload_file(client_factory):
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t")
    form.add_field("path", "")
    form.add_field("file", b"hello-bytes", filename="up.bin",
                   content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload", data=form)
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["status"] == "done"
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=")
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "up.bin" in names


async def test_upload_too_large(client_factory):
    # 1 MB cap, send 2 MB. WriteConfig is imported at the top of this file.
    client = await client_factory(write=WriteConfig(max_upload_mb=1))
    form = FormData()
    form.add_field("root", "t")
    form.add_field("path", "")
    form.add_field("file", b"x" * (2 * 1024 * 1024), filename="big.bin",
                   content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload", data=form)
    assert resp.status == 413
    assert (await resp.json())["error"]["code"] == "UPLOAD_TOO_LARGE"


async def test_upload_rejects_traversal_filename(client_factory):
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t")
    form.add_field("path", "")
    form.add_field("file", b"x", filename="../evil.bin",
                   content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload", data=form)
    assert resp.status == 403


async def test_upload_conflict_returns_409(client_factory):
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t")
    form.add_field("path", "")
    form.add_field("file", b"x", filename="top.txt",  # top.txt already exists in tmp_root
                   content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload", data=form)
    assert resp.status == 409
    assert (await resp.json())["error"]["code"] == "CONFLICT"


async def test_upload_replace_via_query(client_factory):
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t")
    form.add_field("path", "")
    form.add_field("file", b"replaced", filename="top.txt",
                   content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload?on_conflict=replace", data=form)
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["status"] == "done"


async def test_upload_invalid_on_conflict_returns_400(client_factory):
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t")
    form.add_field("path", "")
    form.add_field("file", b"x", filename="new.bin",
                   content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload?on_conflict=bogus", data=form)
    assert resp.status == 400


async def test_upload_skip_existing(client_factory):
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t"); form.add_field("path", "")
    form.add_field("file", b"x", filename="top.txt", content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload?on_conflict=skip", data=form)
    assert resp.status == 200
    assert (await resp.json())["data"]["results"][0]["status"] == "skipped"


async def test_upload_replace_directory_rejected(client_factory):
    # uploading a FILE named "sub" with replace must NOT rmtree the existing sub/ directory
    client = await client_factory()
    form = FormData()
    form.add_field("root", "t"); form.add_field("path", "")
    form.add_field("file", b"x", filename="sub", content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload?on_conflict=replace", data=form)
    assert resp.status == 400
    listing = await client.get("/filemanaty/api/v1/list?root=t&path=sub")
    assert listing.status == 200
    names = [e["name"] for e in (await listing.json())["data"]["entries"]]
    assert "nested.txt" in names  # sub/ tree intact


async def test_truncated_false_at_exactly_max(client_factory, monkeypatch):
    monkeypatch.setattr(api_module, "MAX_LIST_ENTRIES", 3)
    client = await client_factory()
    # tmp_root top level has top.txt + sub (2). Add a 3rd so it holds exactly 3.
    await _post(client, "/filemanaty/api/v1/mkdir", {"root": "t", "path": "", "name": "third"})
    resp = await client.get("/filemanaty/api/v1/list?root=t&path=")
    body = await resp.json()
    assert len(body["data"]["entries"]) == 3
    assert body["data"]["truncated"] is False  # exactly == max is NOT truncated


# ---------------------------------------------------------------------------
# Security hardening: trash dir protection across all write endpoints
# ---------------------------------------------------------------------------

async def test_mkdir_trash_dir_rejected(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/mkdir",
                       {"root": "t", "path": "", "name": ".filemanaty_trash"})
    assert resp.status == 403


async def test_rename_to_trash_dir_rejected(client_factory):
    client = await client_factory()
    resp = await _post(client, "/filemanaty/api/v1/rename",
                       {"root": "t", "path": "top.txt", "name": ".filemanaty_trash"})
    assert resp.status == 403


async def test_copy_into_trash_rejected(client_factory):
    client = await client_factory()
    await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["sub"]})  # creates trash dir
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "t", "dst_path": ".filemanaty_trash"})
    assert resp.status == 403


async def test_move_into_trash_rejected(client_factory):
    client = await client_factory()
    await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["sub"]})
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "t", "src_items": ["top.txt"], "dst_root": "t", "dst_path": ".filemanaty_trash"})
    assert resp.status == 403


async def test_upload_into_trash_rejected(client_factory):
    client = await client_factory()
    await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["sub"]})
    form = FormData()
    form.add_field("root", "t"); form.add_field("path", ".filemanaty_trash")
    form.add_field("file", b"x", filename="evil.txt", content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload", data=form)
    assert resp.status == 403


async def test_restore_rejects_unsafe_meta_name(client_factory, tmp_root):
    import json as _json
    from filemanaty import operations as _ops
    client = await client_factory()
    d = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid = (await d.json())["data"]["results"][0]["id"]
    meta_file = tmp_root / _ops.TRASH_DIRNAME / f"{tid}.meta.json"
    meta = _json.loads(meta_file.read_text())
    meta["original_name"] = "../escape.txt"
    meta_file.write_text(_json.dumps(meta))
    resp = await _post(client, "/filemanaty/api/v1/trash/restore", {"root": "t", "ids": [tid]})
    assert resp.status == 403


async def test_restore_duplicate_targets_keep_both_409(client_factory):
    client = await client_factory()
    d1 = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid1 = (await d1.json())["data"]["results"][0]["id"]
    await _post(client, "/filemanaty/api/v1/mkdir", {"root": "t", "path": "", "name": "top.txt"})
    d2 = await _post(client, "/filemanaty/api/v1/delete", {"root": "t", "items": ["top.txt"]})
    tid2 = (await d2.json())["data"]["results"][0]["id"]
    # both restore to "top.txt"; keep_both would otherwise collide and lose data
    resp = await _post(client, "/filemanaty/api/v1/trash/restore",
                       {"root": "t", "ids": [tid1, tid2], "on_conflict": "keep_both"})
    assert resp.status == 409


# ---------------------------------------------------------------------------
# Read-only root enforcement (B3)
# ---------------------------------------------------------------------------

async def test_ro_mkdir_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/mkdir", {"root": "ro", "path": "", "name": "fresh"})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_rename_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/rename", {"root": "ro", "path": "top.txt", "name": "x.txt"})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_delete_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/delete", {"root": "ro", "items": ["top.txt"]})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_upload_rejected(ro_rw_client):
    client = await ro_rw_client()
    form = FormData()
    form.add_field("root", "ro"); form.add_field("path", "")
    form.add_field("file", b"x", filename="new.txt", content_type="application/octet-stream")
    resp = await client.post("/filemanaty/api/v1/upload", data=form)
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_copy_into_readonly_dst_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "rw", "src_items": ["existing.txt"], "dst_root": "ro", "dst_path": ""})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_copy_from_readonly_src_allowed(ro_rw_client):
    """Copying OUT of a read-only root is fine — the source is only read."""
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/copy", {
        "src_root": "ro", "src_items": ["top.txt"], "dst_root": "rw", "dst_path": ""})
    assert resp.status == 200
    dst = await client.get("/filemanaty/api/v1/list?root=rw&path=")
    assert "top.txt" in [e["name"] for e in (await dst.json())["data"]["entries"]]


async def test_ro_move_out_of_readonly_src_rejected(ro_rw_client):
    """Moving OUT of a read-only root removes from it — a write — so reject."""
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "ro", "src_items": ["top.txt"], "dst_root": "rw", "dst_path": ""})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_move_into_readonly_dst_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/move", {
        "src_root": "rw", "src_items": ["existing.txt"], "dst_root": "ro", "dst_path": ""})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_trash_restore_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/trash/restore", {"root": "ro", "ids": ["anything"]})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_ro_trash_purge_rejected(ro_rw_client):
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/trash/purge", {"root": "ro", "all": True})
    assert resp.status == 403
    assert (await resp.json())["error"]["code"] == "READ_ONLY"


async def test_rw_root_still_writable(ro_rw_client):
    """Regression: the writable root in the same config still accepts writes."""
    client = await ro_rw_client()
    resp = await _post(client, "/filemanaty/api/v1/mkdir", {"root": "rw", "path": "", "name": "fresh"})
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
