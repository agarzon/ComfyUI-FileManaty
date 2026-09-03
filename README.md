<p align="center">
  <img src="assets/screenshot.jpg" alt="FileManaty — seamless file management for ComfyUI" width="100%">
</p>

<h1 align="center">ComfyUI-FileManaty</h1>

<p align="center">
  <strong>The gentle file-manatee for ComfyUI.</strong><br>
  A full file manager <em>inside</em> the ComfyUI web UI — browse, preview, organize,
  upload, rename, move, copy, and trash the files in your ComfyUI roots, without ever
  touching the host OS.
</p>

<p align="center">
  <a href="https://github.com/agarzon/ComfyUI-FileManaty/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/agarzon/ComfyUI-FileManaty?display_name=tag"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <a href="https://wallrus.tech"><img alt="Sponsored by Wallrus" src="https://img.shields.io/badge/sponsored%20by-Wallrus-7c3aed"></a>
</p>

---

## ✨ Features

- 🗂️ **Explorer-style file manager** — a folder tree, a thumbnail grid, and a live preview pane, all in one fullscreen overlay with **drag-resizable panes** (double-click a divider to reset).
- ⭐ **Favorite folders** — pin the folder you're in with **☆ Favorite** in the toolbar; the star turns gold and the folder sits above the tree as a one-click jump, across roots.
- 🖼️ **Rich previews** — inline images, an HTML5 **video** player, and an **audio** player. Generated files show their **resolution** (`1024 × 1024`), size, and date at a glance.
- 🧠 **See the generation behind the file** — embedded ComfyUI metadata (positive/negative prompt, seed, model, LoRAs) surfaced in the preview, with one-click **Copy JSON** and **Load on canvas** to drop the workflow straight onto your graph.
- 📤 **Full write operations** — create folders, rename, upload **files or whole folders** (button or drag from your desktop, with per-file progress, speed, ETA and cancel), copy/cut/paste, and move — within and across roots. A **basket** collects items across folders so one copy, move or delete can act on all of them.
- 📦 **Download a selection as one ZIP** — files, folders or a mix; folders keep their shape, and the browser's own download manager shows bytes, speed and ETA.
- ♻️ **Recoverable trash** — deletes go to one trash view spanning every root, to restore from or purge. `Shift+Delete` removes permanently.
- 🛡️ **Read-only roots** — mount any root browse-only; the server rejects every write and the toolbar hides write actions.
- 🎨 **Native look & feel** — follows your active ComfyUI theme (light, dark, or custom) live, via the same design tokens ComfyUI uses.
- ⌨️ **Fast** — keyboard navigation, multi-select, drag-and-drop, right-click context menus, and `Ctrl+Shift+F` to open.
- 🔒 **Safe by design** — every path is sandboxed to your configured roots server-side (no `..`, no absolute paths, no symlink escapes).

## 📦 Installation

### Option A — ComfyUI Manager (recommended)
Open **ComfyUI Manager → Custom Nodes Manager**, search for **`FileManaty`**, click **Install**, and restart ComfyUI.

### Option B — git clone
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/agarzon/ComfyUI-FileManaty.git
```
Restart ComfyUI.

> **Requirements:** Python 3.10+ and [Pillow](https://python-pillow.org/) (`>=10.0`). Pillow ships with ComfyUI, so there's usually nothing extra to install.

## 🚀 Getting started

1. Open ComfyUI in your browser.
2. Click the **🦭 FileManaty** button in the top action bar — or press **`Ctrl+Shift+F`**.
3. With no config file present, FileManaty auto-mounts ComfyUI's **`output/`**, **`input/`**, and **`workflows`** folders as your browsable roots. Start browsing!

Pick a file to preview it on the right; double-click a folder to enter it. Sort the grid from the toolbar — pick a field and flip the direction with the arrow. Select one or many files (click / `Ctrl`-click / `Shift`-click / `Ctrl+A`), then use the toolbar or right-click menu to manage them.

## ⚙️ Configuration

FileManaty splits configuration into two layers.

### Display preferences — ComfyUI Settings
Open **ComfyUI Settings → 🦭 FileManaty**. These are per-browser display choices:

| Setting | What it does |
|---|---|
| **View → Allow Hidden** | Show dotfiles in listings |
| **View → Show Thumbnails** | Toggle image and video thumbnails |
| **View → Grid Density** | Compact / Normal / Comfortable |
| **View → Thumbnail Size** | Small / Medium / Large |
| **Sort → Field / Order** | Sort by name, size, date, or type — ascending or descending (also in the panel toolbar). Defaults to newest first |
| **Sort → Folders First** | Keep folders above files |
| **Open → Default Root** | Which root opens first (or "Last used") |
| **Confirm → On Delete / On Shift-Delete** | Confirmation dialogs for trashing / permanent delete |

### Deployment policy — `config.json`
For security and capacity limits the server is the authority. Drop a `config.json` in the extension directory (copy `config.example.json` to start) and **restart ComfyUI** to apply.

| Field | Required | Default | Notes |
|---|---|---|---|
| `roots[]` | yes, once a `config.json` exists | auto-mount `output/` + `input/` + workflows | The browsable roots. Auto-mounting applies **only when there is no config file** — a `config.json` that omits `roots` logs a warning and leaves the UI empty |
| `roots[].id` | yes | — | Matches `^[a-z0-9_-]{1,32}$`, unique |
| `roots[].label` | yes | — | Display name shown in the UI |
| `roots[].path` | yes | — | Absolute, **or relative to your ComfyUI install directory** (`"models"` → `D:\ComfyUI\models`), which keeps one config file portable across machines and drives. Must exist and be a directory — a root whose path doesn't resolve is skipped with an error in the log, and the rest of the config still loads |
| `roots[].writable` | no | `true` | Set `false` for a browse-only root |
| `files.image_extensions` | no | png, jpg, jpeg, webp, gif, bmp, avif | Previewed inline + get thumbnails |
| `files.video_extensions` | no | mp4, webm, mkv, mov | Get thumbnails (decoded server-side) + played inline where the browser supports the container |
| `files.audio_extensions` | no | mp3, wav, ogg, m4a, flac | Played inline (HTML5 audio) |
| `thumbnails.max_dimension` | no | `320` | Longest side, `64`–`1024` |
| `write.max_upload_mb` | no | `1024` | Max size per uploaded file, `1`–`1048576`. Counted in MiB — the value is multiplied by `1024 * 1024` — so the default is 1 GiB and the ceiling 1 TiB. See [Uploading big files](#uploading-big-files) |

If the config is malformed or invalid, FileManaty logs a clear error and falls back to the auto-mount defaults — **ComfyUI never crashes**. If the file is valid but a single root's path doesn't resolve, only that root is skipped (with an error naming it in the log) and the rest still loads.

#### A portable config

Paths relative to your ComfyUI install work on any machine and any drive, so the same file can
follow a portable install around:

```json
{
  "roots": [
    { "id": "outputs",   "label": "Outputs",   "path": "output" },
    { "id": "inputs",    "label": "Inputs",    "path": "input" },
    { "id": "workflows", "label": "Workflows", "path": "user/default/workflows" },
    { "id": "models",    "label": "Models",    "path": "models", "writable": false },
    { "id": "archive",   "label": "Archive",   "path": "/mnt/nas/renders" }
  ]
}
```

On a portable Windows install that mounts `D:\ComfyUI\output`, `D:\ComfyUI\models` and so on;
`archive` shows that absolute paths still work when a root lives somewhere else entirely.

**Three things that trip people up:**

- **The moment a `config.json` exists, auto-mounting stops.** You have to list *every* root you
  want, including outputs and inputs — they are not added on top of your file.
- **Your workflows folder is `user/default/workflows`**, and a root from `config.json` will
  **not create it**. Auto-mounting does (the folder often doesn't exist until ComfyUI's first
  save), a configured root does not — so if you haven't saved a workflow yet you'll see
  `skipping root 'workflows' — unusable path …` in the log. Save one workflow, or create the
  folder once.
- **If you launch ComfyUI with `--user-directory` elsewhere**, a hand-written
  `user/default/workflows` won't follow it. Point that root at the real path instead.

#### Uploading big files

Models and LoRAs run to tens of gigabytes, and the default cap is 1 GiB per file. Raise it:

```json
{ "write": { "max_upload_mb": 51200 } }
```

ComfyUI's own `--max-upload-size` (100 MB by default) does **not** apply here — FileManaty streams
uploads in chunks rather than buffering the request body, so `write.max_upload_mb` is the only
limit that matters. Before you rely on it for very large files:

- **There is no resume.** An upload streams to a temporary file next to its destination and is
  discarded if the connection drops, so a failure near the end costs the whole transfer.
- **The cap is enforced as bytes arrive**, so a file over the limit is refused only after being
  sent that far.
- **Keep the destination's free space above the file size** — the temporary file lives there
  until the upload completes.
- **A reverse proxy in front of ComfyUI will have its own limit and timeout**, usually far
  stricter (nginx defaults to 1 MB via `client_max_body_size`).

## 🔒 Security

FileManaty can write to your filesystem, so please read this.

- **No built-in authentication.** Anyone who can reach your ComfyUI HTTP port can use FileManaty. If you expose ComfyUI beyond localhost, put it behind a reverse proxy that handles auth (nginx basic-auth, Caddy forward-auth, Cloudflare Access, …). *(Optional built-in auth is on the roadmap.)*
- **Server-side sandboxing.** The browser only ever sends a root id + relative path. The server resolves it against the configured root and rejects `..`, absolute paths, drive switches, NUL bytes, and symlinks that escape the root.
- **Scope your roots.** Point roots at specific subdirectories — never your home directory or a system drive.
- **Safe previews.** Only images, video, and audio from your allow-lists are served inline (always with `X-Content-Type-Options: nosniff`); HTML/SVG and other active content types are refused, never rendered.

## 🗺️ Roadmap

Shipped recently: ZIP download for a selection, favorite folders, folder upload (drop a folder or pick one), one unified trash, drag-resizable overlay panes, auto-mounted Workflows root, in-folder name + type filter, rich video + audio preview, embedded-metadata cards, Load-on-canvas, and a native theme-following UI. Coming next:

- 🔍 **Server-side & metadata search** — search across a whole root (past the listing cap) and find files by the **prompt / model / seed** that made them. *(In-folder name + type filtering shipped in v0.8.0.)*
- 🔐 **Optional built-in authentication** — a lightweight password mode for small deployments.
- 🖱️ **Right-click menu on the folder tree** (new folder, rename, delete, paste), plus **drag-and-drop within a root** to move items straight in the tree.
- 👁️ **Double-click to open** — full-size image lightbox, inline video/audio player, doc editor, or 3D viewer.
- 📝 **Text / JSON preview** with syntax highlighting — later, inline editing + save.
- 🧊 **3D model preview** (Load3D).
- 📤 **Send to input** — move an output into `input/` in one click.

Ideas and feedback are very welcome — open an [issue](https://github.com/agarzon/ComfyUI-FileManaty/issues).

## 🐾 The story behind the name

**FileManaty** is a small pile of puns: a **file manager** that's secretly a **manatee** 🐾, with a dash of **mana** — a little generative magic, fitting for its ComfyUI habitat. Slow, calm, and dependable is exactly how you want something looking after your files.

It comes from **Wallrus**, whose own name blends a *social **wall*** with a ***walrus***. Two friendly sea mammals, one idea: tools that are unhurried, sturdy, and easy to live with.

## 💙 Sponsored by Wallrus

FileManaty is proudly sponsored by **[Wallrus](https://wallrus.tech)**. If FileManaty makes your ComfyUI workflow nicer, go say hi. 🦭

## 🛠️ Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest -q
```

### Smoke testing with Docker
```bash
docker compose -f docker/docker-compose.yml up -d   # ComfyUI at http://localhost:8188
```
The repo is bind-mounted into the container's `custom_nodes/`. Edit on the host, then restart the container for Python changes and hard-reload the browser for JavaScript changes. Pin a ComfyUI version with `--build-arg COMFYUI_REF=v0.3.27` on `docker compose build`.

Thumbnails are cached as WebP under `<ComfyUI user dir>/filemanaty/thumbs/`, mirroring each root's folder layout — safe to delete at any time; they regenerate on demand and survive ComfyUI updates. A cached thumbnail is dropped as soon as its source file is deleted, moved, renamed, or overwritten, so no thumbnail outlives the image it came from. Changes made outside FileManaty are caught the next time you browse the folder.

## 📄 License

[MIT](LICENSE) © 2026 Alexander Garzon
