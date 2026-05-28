# ComfyUI-FileManaty

A read-only file viewer for ComfyUI. Browse approved folders, see image thumbnails, preview full-res images, and download files — all from inside the ComfyUI web UI, without OS access to the host.

## Install

### Option A: ComfyUI Manager
Search for `ComfyUI-FileManaty` and install. Restart ComfyUI.

### Option B: clone
```
cd ComfyUI/custom_nodes
git clone https://github.com/<owner>/ComfyUI-FileManaty.git
```
Restart ComfyUI.

## First run

With no config file present, the extension auto-mounts ComfyUI's `output/` and `input/` directories as the two browsable roots. Open ComfyUI in your browser — you should see a **Files** button in the topbar and a **Files** entry in the sidebar.

## Configuration

Drop a `config.json` in the extension directory. Use `config.example.json` as a starting point. Restart ComfyUI to apply changes.

Schema:

| Field | Required | Default | Notes |
|---|---|---|---|
| `roots[]` | yes | auto-mount input + output | Each root has `id`, `label`, `path` (absolute) |
| `roots[].id` | yes | — | Matches `^[a-z0-9_-]{1,32}$`, unique |
| `roots[].writable` | no | `true` | Set `false` for a browse-only root; the server rejects all write operations and the UI disables write actions |
| `files.allow_hidden` | no | `false` | Show dotfiles in listings |
| `files.image_extensions` | no | png/jpg/jpeg/webp/gif/bmp/avif | Lowercase, dot-prefixed |
| `thumbnails.enabled` | no | `true` | Disable to skip thumbnail generation |
| `thumbnails.max_dimension` | no | `320` | 64..1024, longest side |
| `write.max_upload_mb` | no | `1024` | Maximum size per uploaded file, in megabytes (1..1048576) |

### Write operations

v0.2.0 adds file-management operations (create folder, rename, delete to a
recoverable trash, copy, move, upload). They are guarded by the same root
sandbox as browsing and by in-UI confirmation dialogs. There is **no
built-in authentication** — deploy behind a reverse proxy with auth for any
non-local exposure.

- `write.max_upload_mb` (default `1024`): maximum size per uploaded file, in
  megabytes.
- `roots[].writable` (default `true`): set `false` to mount a root browse-only.
  Every mutating endpoint (mkdir, rename, delete, copy, move, upload, trash
  restore/purge) is rejected server-side with `403 READ_ONLY`, and the toolbar
  disables its write buttons. Copying *out of* a read-only root into a writable
  one is still allowed; moving out of it is not (a move deletes the source).

Deleted items go to a hidden `.filemanaty_trash/` folder inside each root
and can be restored from the Trash view; `Shift+Delete` deletes permanently.
The trash is not auto-evicted in v0.2.0 — empty it from the Trash view.

If the config is malformed or invalid, the extension logs a clear error and falls back to defaults. ComfyUI does not crash.

## Security notes

- **Sandboxing is enforced server-side.** The frontend never sends raw absolute paths to the backend; only root id + relative path. Server-side `safe_resolve` rejects `..`, absolute paths, drive switches, NUL bytes, and symlinks that escape the root.
- **No built-in authentication in v1.** Whoever can reach ComfyUI's HTTP port can use this extension. If you expose ComfyUI to the internet, put it behind a reverse proxy that handles auth (nginx + basic auth, Caddy + forward-auth, Cloudflare Access, etc.).
- **Do not map a root to your home directory or system drive.** Restrict roots to specific subdirectories.
- **Symlinks inside a root are followed.** Anything they reach must stay inside the root or it's rejected.
- **Hidden files are blocked by default.** Set `files.allow_hidden: true` to expose them (not recommended for shared deployments).
- **`/preview` is restricted to image extensions** to prevent stored XSS via HTML/SVG in a managed folder.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -v
```

### Smoke testing with Docker

```bash
docker compose -f docker/docker-compose.yml up -d
# ComfyUI runs at http://localhost:8188
```

The repo is bind-mounted into `custom_nodes/comfyui-filemanaty` inside the container. Edit files on the host; restart the container to reload Python; reload the browser to reload JavaScript.

To pin a specific ComfyUI version:
```bash
docker compose -f docker/docker-compose.yml build --build-arg COMFYUI_REF=v0.3.27
```

### Thumbnail cache

Cached as WebP under `<ComfyUI user dir>/filemanaty/thumbs/`. Safe to delete at any time; the cache regenerates on demand. The cache lives outside `custom_nodes/` so ComfyUI updates don't wipe it.

## License

MIT.
