# Changelog

## v0.5.7 — 2026-06-01

### Changed

- The metadata card's two copy buttons ("Copy workflow JSON" / "Copy prompt JSON")
  are now a single **Copy JSON** button. It copies the full UI workflow when present
  (the editable, shareable graph) and falls back to the API prompt for files that
  embed only that — removing redundant, near-identical buttons while keeping coverage.

## v0.5.6 — 2026-06-01

### Fixed

- **Copy workflow/prompt JSON now works on non-HTTPS servers.** The metadata
  card's Copy buttons relied on `navigator.clipboard`, which browsers expose only
  in secure contexts (HTTPS or localhost). On a ComfyUI server reached over plain
  HTTP at a LAN address it is `undefined`, so the buttons silently did nothing.
  Added a `document.execCommand("copy")` fallback (via a temporary textarea) and a
  "Copy failed" toast so the action works — and reports — in insecure contexts too.

## v0.5.5 — 2026-06-01

### Added

- **Load workflow on canvas.** The preview metadata card now has a "Load on
  canvas" button (shown whenever a file carries an embedded `workflow` or
  `prompt`). It hands the raw file to ComfyUI's own load-from-file path, so any
  format/embedding ComfyUI supports is loaded onto the node editor, then closes
  the file manager so the canvas is visible. Frontend-only — reuses the existing
  `/download` route, no new backend surface.

## v0.5.0 — 2026-06-01

### Added

- Preview panel now shows embedded ComfyUI metadata for generated files. A
  best-effort card surfaces positive/negative prompt, seed, model, and LoRAs;
  the full embedded `workflow`/`prompt` JSON is available via Copy-as-JSON.
  New read-only `GET /filemanaty/api/v1/metadata` endpoint. Format support:
  PNG (`tEXt`/`iTXt`), WebP/JPEG (EXIF, including the UserComment sub-IFD), and
  MP4/WebM/MKV/MOV (PyAV, optional — degrades gracefully when PyAV is absent). Extraction
  never breaks the panel: unknown or custom graphs degrade each field to `—`.

### Fixed

- Pressing Esc to cancel a dialog (e.g. the delete-to-Trash confirmation) no
  longer closes the whole file manager. Dialogs now trap Esc and resolve as
  cancel; the overlay's Esc handler defers to any open dialog.
- The selection can now be cleared: clicking empty grid space deselects, and Esc
  clears the selection before (a second Esc) closes the overlay — so the toolbar
  no longer stays stuck at "1 selected".
- The Refresh button now refreshes the folder tree as well as the grid.
- The Refresh button gains an icon, for consistency with the other toolbar buttons.

## v0.4.1 — 2026-06-01

### Fixed

- Grid rows no longer overlap when a folder has many images. The cells' `aspect-ratio`
  was not feeding the CSS grid's automatic row track, so rows collapsed toward the
  caption's min-content height while cells rendered full size — stacking images over
  the rows below. The grid now uses an explicit `grid-auto-rows` (the thumbnail size)
  instead of `aspect-ratio`, so every row is the right height. This also fixes the
  selection outline appearing to wrap more than the selected image (it was the
  overlapping cell, not the image).

## v0.4.0 — 2026-06-01

### Fixed

- Overlay, dialogs, context menu, and toasts now follow ComfyUI's active theme
  (light/dark/custom) via its palette tokens, instead of being hard-coded dark.
  Colors are driven by a set of semantic `--fm-*` variables aliasing ComfyUI's
  PrimeVue `--p-*` tokens, so the file manager recolors live when the theme changes.
- Preview pane no longer jumps when navigating between images of different aspect
  ratios. The preview image is now clamped to the pane height (`#fm-preview` gets
  `min-height:0; overflow:hidden`), so the filename/actions block stays put instead
  of being pushed off-screen by tall images.

## v0.3.2 — 2026-06-01

First public release. No runtime behavior changes since v0.3.1.

### Added

- Project visual identity (manatee mascot banner) and an origin story in the README.

### Changed

- Contributor/test dependencies moved into a `[project.optional-dependencies]` `test`
  extra (`pip install -e ".[test]"`); removed the standalone `requirements-dev.txt`.
- Package metadata: repository URL, description, and version updated for publication.

## v0.3.1 — 2026-05-29

Polish on top of v0.3.0. No behavior changes, no new features.

### Fixed

- `renderGrid` now uses the already-hoisted `childPath` local for the
  clipboard-cut-highlight check and the drop-target wiring, instead of
  re-computing it via `childPathOf(e.name)` at each call site. Functionally
  identical; removes the incomplete-hoist tail from the v0.3.0 refactor.
- `settings.subscribe`'s returned unsubscribe function now removes the
  subscriber `Set` from the internal `Map` when it becomes empty, instead
  of leaving empty `Set`s pinned forever. Negligible in practice (we have
  a fixed catalog of 10 setting keys), but the cleanup matches the
  semantic intent.

### Docs

- v0.3.0 CHANGELOG entry for `Open.DefaultRoot` clarified: the setting is
  evaluated when the overlay initializes, which happens once per page
  load. Changing it does not affect an already-open or close+reopened
  overlay — only the next full page reload picks it up.

## v0.3.0 — 2026-05-28

ComfyUI Settings system migration. Every user-facing preference now lives in
the ComfyUI Settings dialog under the **FileManaty** category. Server-side
configuration (`config.json`) shrinks to deployment policy that the server
enforces and that browser clients cannot override.

### Added

- **FileManaty Settings dialog section** with 10 settings: `View.AllowHidden`,
  `View.ShowThumbnails`, `View.GridDensity` (compact/normal/comfortable),
  `View.ThumbnailSize` (small/medium/large), `Sort.Field`
  (name/size/mtime/type), `Sort.Order` (asc/desc), `Sort.FoldersFirst`,
  `Open.DefaultRoot`, `Confirm.OnDelete`, `Confirm.OnShiftDelete`.
- New `web/settings.js` module — single adapter over ComfyUI's Settings API.
- New `/list?include_hidden=true|false` query parameter — strict bool parse
  (`true`/`false`/`1`/`0` case-insensitive); anything else → `400`.

### Changed

- `/list` now reads `include_hidden` from the request, not config. Default
  (param absent) = `false`.
- Grid sort is now driven by `Sort.Field` / `Sort.Order` /
  `Sort.FoldersFirst` instead of a hardcoded name-asc + folders-first.
- Default-root-on-open is driven by `Open.DefaultRoot`. The literal value
  `"Last used"` preserves the previous behavior; a specific root id opens
  there directly. Stale root ids fall back to the first available root.
  Evaluated when the overlay is initialized for the first time per page
  load — close+reopen reuses the already-initialized state, so changing
  this setting takes effect after the next page reload.
- `web/filemanaty.js`: `localStorage.lastRoot` is now read only when
  `DefaultRoot = Last used`.

### Removed

- `files.allow_hidden` and `thumbnails.enabled` keys from `config.json`. Old
  configs containing these keys still parse (silently ignored). Equivalent
  toggles live in the Settings dialog now.
- The server-side `thumbnails.enabled` gate on `/thumbnail`. Whether thumbs
  render is now a pure client display choice (`View.ShowThumbnails`).
- The ability to create dot-prefixed filenames via `/mkdir`, `/rename`,
  `/upload`. Previously gated by `files.allow_hidden=true`; now always
  disallowed via `safe_name`. Hidden files created out-of-band (e.g.
  `.bashrc`) can still be surfaced in the listing by toggling
  `View.AllowHidden`.

### Security

- **Trust Boundary** rule introduced: server-side settings (roots, paths,
  writable flags, image_extensions allowlist, thumbnail max dimension,
  upload size cap) cannot be overridden by client requests. The server
  validates every client-supplied value against config; out-of-policy =
  `400`/`403`, never a silent override. Documented in
  §4.

### Fixed

- Settings changes (sort, density, thumbnail size, etc.) reflect immediately
  in the grid. The settings.js adapter now caches values in onChange so
  subscribers (e.g. `renderGrid`) read the new value synchronously instead
  of racing the ComfyUI store update.

### Known consequence (UX quirk — reconsider in v0.4)

- Toggling `View.AllowHidden = true` makes dotfiles **visible in listings**
  but `/preview`, `/download`, `/thumbnail`, and all write endpoints still
  return `403 ACCESS_DENIED` for paths containing a dot-prefixed component.
  This is intentional defense-in-depth for v0.3.0; v0.4.0 may plumb the
  per-request include-hidden value through every endpoint if the
  listing-only behavior proves limiting.

### Tests

- Backend: full suite green (target: ~240 passing, 1 platform-conditional
  skip). New `include_hidden` cases in `tests/test_api.py`; new legacy-key
  ignore cases in `tests/test_config.py`.
- Frontend: smoke-tested via Docker + Playwright MCP per the spec §8.2
  checklist.

## v0.2.1 — 2026-05-28

Hardening and UX polish on the v0.2.0 file manager.

### Added

- **Read-only roots.** A root may set `"writable": false` in `config.json` to be mounted browse-only. Every mutating endpoint (mkdir, rename, delete, copy/move destination, move source, upload, trash restore/purge) is rejected server-side with `403 READ_ONLY`, and the toolbar disables its write buttons for that root. Copying *out of* a read-only root is still allowed; moving out of it is not. The `/roots` response now includes each root's `writable` flag.

### Fixed

- **Thumbnail cache write race.** Concurrent requests for the same uncached thumbnail shared one temp file (named by PID, constant within the process) and could corrupt each other's bytes before the atomic swap. Each stage now uses a unique random temp name, matching the upload path.

### Security

- `safe_name()` now rejects Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, case-insensitive, with or without an extension) so a tree created on Linux stays portable to Windows hosts.

### Changed (frontend)

- New Folder and Rename now route name collisions through the Replace / Keep both / Skip conflict dialog (previously a dead-end "already exists" toast).
- Instant client-side feedback for the always-invalid name cases (slashes, trailing dot) before hitting the server.
- Breadcrumb shows the root's configured label instead of its id.

### Tests

- Backend: 234 passing, 1 platform-conditional skip. Frontend verified by browser smoke testing (read-only button states, conflict dialog, name validation, breadcrumb label) in the Docker dev environment.

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
