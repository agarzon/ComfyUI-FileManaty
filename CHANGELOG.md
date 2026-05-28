# Changelog

## v0.2.0 — 2026-05-28

Turns the read-only viewer into a full Explorer-style file manager.

### Features

- Folder tree pane (left) showing all configured roots, lazy-expanded (caret toggles; clicking a folder navigates into it).
- Multi-select in the grid (click / Ctrl-click / Shift-click / Ctrl-A).
- Create folder, rename, and upload (toolbar button + drag files from the OS desktop). Any file type; size capped by `write.max_upload_mb` (default 1 GB).
- Delete to a recoverable, per-root trash (`.filemanaty_trash/`); Shift+Delete deletes permanently. Trash view to restore, purge, or empty.
- Copy / cut / paste (Ctrl+C/X/V) and move, within and across roots.
- Drag-and-drop move (or copy with Ctrl held) onto folders and tree nodes.
- Right-click context menus on items and empty space.
- Explorer-style conflict handling: Replace / Keep both / Skip, via a 409-driven retry flow.
- Result toasts for uploads and bulk operations.

### Security

- All write operations funnel through the same `safe_resolve` chokepoint; cross-root operations validate both source and destination. New `safe_name()` rejects path separators, control characters, `.`/`..`, and (by default) dotfiles in new names. Operations refuse to touch a configured root itself or the `.filemanaty_trash` directory (across every write endpoint), and refuse moving a folder into its own descendant. Uploads are size-capped while streaming. Replace operations use a temp-then-atomic-swap so a mid-operation failure never destroys existing data.
- Trust model unchanged: no built-in authentication — deploy behind a reverse proxy for any non-local exposure.

### Fixed

- `truncated` flag off-by-one at exactly `MAX_LIST_ENTRIES` entries.
- Thumbnail cache key now canonicalizes `.` path segments (no duplicate cache entries for equivalent paths).

### Tests

- Backend: 194 passing, 1 platform-conditional skip. Frontend verified by browser smoke testing in the Docker dev environment.

### Known limitations (deferred to v0.3.0+)

- No trash auto-eviction — empty the trash manually from the Trash view.
- No built-in auth, server-side search/sort/filter, video thumbnails, audit log, or dual-pane mode.

## v0.1.0-rc3 — 2026-05-28

First release candidate considered ready for personal use. Read-only file viewer for ComfyUI.

### Features

- ComfyUI extension entry points: topbar "Files" button, sidebar tab, and `Ctrl+Shift+F` keyboard shortcut — all open the same fullscreen overlay.
- Overlay layout: grid view on the left, persistent preview pane on the right, breadcrumb + root tabs along the top.
- Auto-mount of ComfyUI's `input/` and `output/` directories as the two default browsable roots (override via `config.json`).
- Image thumbnails: WebP, on-disk cached at `<ComfyUI user dir>/filemanaty/thumbs/`, mtime-keyed so edits regenerate automatically.
- Image preview (inline) + file download (attachment) for any file in a configured root.
- Keyboard navigation inside the overlay: arrow keys move selection, Enter enters a folder, Backspace goes up one level, ESC closes the overlay.
- Per-browser persistence of last selected root via `localStorage`.

### Security

- All user-supplied paths funnel through a single `safe_resolve` chokepoint.
- Adversarial test coverage: `..` traversal in many forms, absolute Unix/Windows paths, drive letters, NUL bytes, UNC paths, and symlinks pointing outside the configured root.
- `/preview` restricted to image extensions to block stored-XSS via HTML/SVG.
- All server-supplied strings escaped before being interpolated into `innerHTML`.
- Hidden files and files inside hidden directories blocked by default (opt-in via `files.allow_hidden`).
- `X-Content-Type-Options: nosniff` on every file-serving response.
- `Content-Disposition` correctly quotes filenames and supports UTF-8 via RFC 5987.

### Architecture

- Backend (Python ≥3.10): four modules — `config.py`, `security.py`, `thumbs.py`, `api.py` — attached to ComfyUI's existing aiohttp server.
- Frontend: two ES modules in `web/` — `api.js` (fetch wrapper), `filemanaty.js` (overlay UI). No bundler, no transpile.
- All file I/O on the response path runs through `run_in_executor`; the aiohttp loop never blocks on filesystem calls.
- Single dependency beyond what ComfyUI already ships: `Pillow>=10.0`.

### Tests

- 82 passing, 1 platform-conditional skip (Windows-only backslash test on Linux).
- Coverage: config (11), security (32), thumbnails (8), API integration (31).
- Docker dev container with ComfyUI for manual smoke testing.

### Known limitations (deferred to v0.2.0)

- No write operations — upload, rename, delete, move, copy, create folder.
- No built-in authentication — deploy behind a reverse proxy for any non-local exposure.
- No video thumbnails — image formats only.
- No server-side search, sort, or filter — client does sort/filter on its own.
- `truncated` flag is a false positive when a directory has exactly 5000 entries.
- Thumbnail cache never evicts — admin clears `<ComfyUI user dir>/filemanaty/thumbs/` manually.
- No folder tree pane on the left (single-pane grid + preview).
- Cache key uses the raw query path, so `sub/./img.png` and `sub/img.png` generate separate cache entries (correctness is fine; wasted disk only).

### Verified on

- Python 3.11 / Pillow 12 / aiohttp 3.13 / pytest 9
- ComfyUI: master branch via the project's Docker dev environment
- WSL2 (Ubuntu) and recent Chromium for the frontend
