import { app } from "../../scripts/app.js";
import { fetchRoots, fetchAbout, fetchList, thumbnailURL, previewURL, downloadURL, fetchMetadata, mkdir as apiMkdir, rename as apiRename, del as apiDel, uploadFiles as apiUpload } from "./api.js";
import { doCopy, doCut, doPaste, runWithConflicts } from "./clipboard.js";
import { clickSelect, selectAll } from "./selection.js";
import { promptText, confirmDialog, toast, trashView, isDialogOpen } from "./dialogs.js";
import { attachContextMenu } from "./contextmenu.js";
import { renderTree } from "./tree.js";
import { makeDraggable, makeDropTarget } from "./dnd.js";
import * as settings from "./settings.js";
import { buildSettingsDefinitions, KEYS as SETTINGS_KEYS } from "./settings.js";

export function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// Maps ComfyUI's live PrimeVue theme tokens to our semantic --fm-* vars (with
// dark fallbacks). Injected once on :root so dialogs/menus/toasts (which mount on
// document.body, outside the overlay) inherit them too.
function injectThemeTokens() {
    if (document.getElementById("fm-theme-tokens")) return;
    const style = document.createElement("style");
    style.id = "fm-theme-tokens";
    style.textContent = `:root{
        --fm-bg: var(--p-content-background, #18181b);
        --fm-bg-elevated: var(--p-overlay-popover-background, #1e1e1e);
        --fm-bg-input: var(--p-form-field-background, #181818);
        --fm-text: var(--p-text-color, #ddd);
        --fm-text-muted: var(--p-text-muted-color, #888);
        --fm-border: var(--p-content-border-color, #333);
        --fm-hover: var(--p-content-hover-background, #2a2a2a);
        --fm-accent: var(--p-primary-color, #0a84ff);
        --fm-on-accent: var(--p-primary-contrast-color, #fff);
        --fm-danger: #d9433f;
        --fm-accent-soft: color-mix(in srgb, var(--fm-accent), transparent 80%);
        --fm-scrim: rgba(0,0,0,.5);
    }`;
    document.head.appendChild(style);
}

const REPO_URL = "https://github.com/agarzon/ComfyUI-FileManaty";

// Single source for the manatee mark — rendered inline in the header logo and
// reused as a CSS mask for the top action-bar button icon. Shapes have no fill,
// so `fill` (inline) or `background-color` through the mask (button) controls color.
const MANATEE_SVG = `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><ellipse cx="34" cy="32" rx="21" ry="14.5"/><ellipse cx="16" cy="37" rx="9.5" ry="8.5"/><path d="M50 23c9-4 14 2 12 11 2 9-3 15-12 11-3-1-5-5-5-11s2-10 5-11z"/><ellipse cx="26" cy="46" rx="4.3" ry="7.6" transform="rotate(22 26 46)"/><ellipse cx="37" cy="47" rx="4" ry="7" transform="rotate(7 37 47)"/></svg>`;

const GITHUB_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 014 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>`;

let cachedVersion = null;

// The action-bar button lives in ComfyUI's topbar, outside #filemanaty-overlay, so
// its icon CSS must be global. Mask + currentColor makes the manatee inherit the
// theme color exactly like native PrimeIcons.
function injectBrandStyles() {
    if (document.getElementById("fm-brand-styles")) return;
    const uri = `data:image/svg+xml,${encodeURIComponent(MANATEE_SVG)}`;
    const style = document.createElement("style");
    style.id = "fm-brand-styles";
    style.textContent = `.fm-icon-manatee{display:inline-block;width:1.15rem;height:1.15rem;`
        + `background-color:currentColor;-webkit-mask:url("${uri}") center/contain no-repeat;`
        + `mask:url("${uri}") center/contain no-repeat}`;
    document.head.appendChild(style);
}

export function childPathOf(name) {
    return STATE.currentPath ? `${STATE.currentPath}/${name}` : name;
}

// Fast client-side feedback for the always-invalid cases. The backend remains
// the authority and reports config-dependent rejections (hidden names when
// allow_hidden is off, reserved device names, control chars) via its own error.
export function validateName(name) {
    if (name.includes("/") || name.includes("\\")) return "Name can’t contain a slash.";
    if (name.endsWith(".")) return "Name can’t end with a dot.";
    return null;
}

// Whether the currently-open root accepts writes (read-only roots disable
// write actions in the toolbar). Defaults to writable if unknown.
export function currentRootWritable() {
    const r = STATE.roots.find((x) => x.id === STATE.currentRoot);
    return r ? r.writable !== false : true;
}

export function selectedPaths() {
    return [...STATE.selected].map(childPathOf);
}

export function rerender() {
    renderGrid();
    renderPreview();
}

export const STATE = {
    overlay: null,
    open: false,
    currentRoot: null,
    currentPath: "",
    entries: [],
    selected: new Set(),   // names selected in the current folder
    anchorName: null,      // last single-clicked name, for Shift-range
    clipboard: null,       // { op: "copy"|"cut", root, paths: [relPath...] }
    roots: [],
};

function openOverlay() {
    injectThemeTokens();
    injectBrandStyles();
    if (!STATE.overlay) {
        STATE.overlay = buildOverlay();
        document.body.appendChild(STATE.overlay);
        initOverlay().catch((e) => console.error("filemanaty init failed:", e));
    }
    STATE.overlay.style.display = "flex";
    STATE.open = true;
}

function closeOverlay() {
    if (STATE.overlay) {
        STATE.overlay.style.display = "none";
    }
    STATE.open = false;
}

function buildOverlay() {
    const root = document.createElement("div");
    root.id = "filemanaty-overlay";
    root.style.cssText = [
        "position:fixed",
        "inset:0",
        "z-index:9000",
        "background:var(--fm-bg)",
        "color:var(--fm-text)",
        "display:flex",
        "flex-direction:column",
    ].join(";");
    root.innerHTML = `
        <div id="fm-header" style="display:flex;justify-content:space-between;align-items:center;padding:8px 14px;border-bottom:1px solid var(--fm-border);background:var(--fm-bg-elevated);">
            <div class="fm-brand">
                <span class="fm-logo">${MANATEE_SVG}</span>
                <span class="fm-name">File<span class="fm-name-accent">Manaty</span></span>
                <span class="fm-ver" id="fm-version"></span>
            </div>
            <div class="fm-head-right">
                <a class="fm-gh" href="${REPO_URL}" target="_blank" rel="noopener" title="View source on GitHub">${GITHUB_SVG}<span>GitHub</span></a>
                <button id="fm-close" title="Close" style="background:none;border:0;color:inherit;font-size:18px;cursor:pointer;line-height:1">✕</button>
            </div>
        </div>
        <div id="fm-tabs" style="display:flex;gap:4px;padding:6px 14px;border-bottom:1px solid var(--fm-border);background:var(--fm-bg-elevated);"></div>
        <input id="fm-file-input" type="file" multiple style="display:none">
        <div id="fm-toolbar" style="display:flex;align-items:center;gap:6px;padding:6px 14px;border-bottom:1px solid var(--fm-border);font-size:12px;color:var(--fm-text-muted);">
            <span id="fm-breadcrumb"></span>
            <span style="flex:1"></span>
            <span id="fm-selcount" style="opacity:.7;margin-right:6px"></span>
            <button class="fm-tb" data-act="newfolder">＋ New Folder</button>
            <button class="fm-tb" data-act="upload">⬆ Upload</button>
            <button class="fm-tb" data-act="rename">✎ Rename</button>
            <button class="fm-tb" data-act="copy">⧉ Copy</button>
            <button class="fm-tb" data-act="cut">✂ Cut</button>
            <button class="fm-tb" data-act="paste">📋 Paste</button>
            <button class="fm-tb" data-act="trash">♻ Trash</button>
            <button class="fm-tb danger" data-act="delete">🗑 Delete</button>
            <button id="fm-refresh" class="fm-tb">↻ Refresh</button>
        </div>
        <div id="fm-body" style="flex:1;display:grid;grid-template-columns:200px 1fr 34%;min-height:0;">
            <div id="fm-tree" style="overflow:auto;padding:8px;border-right:1px solid var(--fm-border);background:var(--fm-bg);font-size:13px;"></div>
            <div id="fm-grid" style="overflow:auto;padding:10px;display:grid;gap:8px;align-content:start;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));"></div>
            <div id="fm-preview" style="border-left:1px solid var(--fm-border);padding:14px;display:flex;flex-direction:column;gap:10px;background:var(--fm-bg);min-height:0;overflow:hidden;"></div>
        </div>
    `;
    const style = document.createElement("style");
    style.textContent = `#filemanaty-overlay .fm-tb{background:var(--fm-hover);border:0;color:inherit;padding:4px 10px;border-radius:3px;cursor:pointer;font-size:12px}
#filemanaty-overlay .fm-tb:hover{background:var(--fm-border)}
#filemanaty-overlay .fm-tb.danger{color:var(--fm-danger)}
#filemanaty-overlay .fm-brand{display:flex;align-items:center;gap:10px}
#filemanaty-overlay .fm-logo{display:inline-flex;width:26px;height:26px;flex:0 0 auto}
#filemanaty-overlay .fm-logo svg{width:100%;height:100%;fill:var(--fm-accent)}
#filemanaty-overlay .fm-name{font-size:15px;font-weight:700;letter-spacing:.2px;color:var(--fm-text)}
#filemanaty-overlay .fm-name-accent{color:var(--fm-accent)}
#filemanaty-overlay .fm-ver{font-size:11px;color:var(--fm-text-muted);background:var(--fm-bg-input);border:1px solid var(--fm-border);padding:1px 8px;border-radius:999px;font-variant-numeric:tabular-nums;letter-spacing:.3px}
#filemanaty-overlay .fm-ver:empty{display:none}
#filemanaty-overlay .fm-head-right{display:flex;align-items:center;gap:16px}
#filemanaty-overlay .fm-gh{display:inline-flex;align-items:center;gap:6px;color:var(--fm-text-muted);text-decoration:none;font-size:12px;transition:color .15s}
#filemanaty-overlay .fm-gh:hover{color:var(--fm-text)}
#filemanaty-overlay .fm-gh svg{width:15px;height:15px}`;
    root.appendChild(style);
    return root;
}

// Fill the header version pill from /about (cached). Best-effort: on failure the
// pill stays empty and is hidden by the `.fm-ver:empty` rule.
async function loadVersion() {
    const el = document.getElementById("fm-version");
    if (!el) return;
    try {
        if (cachedVersion == null) cachedVersion = (await fetchAbout()).version;
        if (cachedVersion) el.textContent = `v${cachedVersion}`;
    } catch { /* leave pill empty */ }
}

async function initOverlay() {
    document.getElementById("fm-close").addEventListener("click", closeOverlay);
    loadVersion();
    document.addEventListener("keydown", (e) => {
        if (!STATE.open) return;
        if (e.key === "Escape") {
            if (isDialogOpen()) return;              // a dialog handles its own Esc
            if (STATE.selected.size) {               // Esc clears selection before closing
                STATE.selected.clear(); STATE.anchorName = null; rerender();
                e.preventDefault(); return;
            }
            closeOverlay(); return;
        }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
            selectAll(); e.preventDefault(); return;
        }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") { doCopy(); e.preventDefault(); return; }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "x") { doCut(); e.preventDefault(); return; }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") { doPaste().catch((x) => toast(x.message, "error")); e.preventDefault(); return; }

        const grid = sortedEntries();
        const current = STATE.selected.size === 1 ? [...STATE.selected][0] : STATE.anchorName;
        const idx = grid.findIndex((entry) => entry.name === current);
        const cols = computeGridColumns();
        if (e.key === "ArrowRight" && idx < grid.length - 1) {
            const name = grid[idx + 1].name;
            STATE.selected = new Set([name]); STATE.anchorName = name;
            e.preventDefault();
        } else if (e.key === "ArrowLeft" && idx > 0) {
            const name = grid[idx - 1].name;
            STATE.selected = new Set([name]); STATE.anchorName = name;
            e.preventDefault();
        } else if (e.key === "ArrowDown" && idx + cols < grid.length) {
            const name = grid[idx + cols].name;
            STATE.selected = new Set([name]); STATE.anchorName = name;
            e.preventDefault();
        } else if (e.key === "ArrowUp" && idx - cols >= 0) {
            const name = grid[idx - cols].name;
            STATE.selected = new Set([name]); STATE.anchorName = name;
            e.preventDefault();
        } else if (e.key === "Enter") {
            const sel = grid[idx];
            if (sel && sel.type === "dir") {
                const next = STATE.currentPath ? `${STATE.currentPath}/${sel.name}` : sel.name;
                navigateTo(STATE.currentRoot, next);
                e.preventDefault();
            }
        } else if (e.key === "Backspace") {
            if (STATE.currentPath !== "") {
                const parts = STATE.currentPath.split("/");
                parts.pop();
                navigateTo(STATE.currentRoot, parts.join("/"));
                e.preventDefault();
            }
        } else if (e.key === "F2") { actRename().catch((x) => toast(x.message, "error")); e.preventDefault(); return; }
        else if (e.key === "Delete") { actDelete(e.shiftKey).catch((x) => toast(x.message, "error")); e.preventDefault(); return; }
        else {
            return;
        }
        renderGrid();
        renderPreview();
    });
    document.querySelectorAll("#fm-toolbar .fm-tb").forEach((b) => {
        const act = b.dataset.act;
        if (act) b.addEventListener("click", () => onToolbarAction(act));
    });
    document.getElementById("fm-refresh").addEventListener("click", () => refresh());

    const fileInput = document.getElementById("fm-file-input");
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) uploadFileList(fileInput.files).catch((x) => toast(x.message, "error"));
        fileInput.value = "";
    });

    const gridEl = document.getElementById("fm-grid");
    gridEl.addEventListener("dragover", (e) => {
        if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) {
            e.preventDefault();
            gridEl.style.outline = "2px dashed var(--fm-accent)";
        }
    });
    gridEl.addEventListener("dragleave", () => { gridEl.style.outline = "none"; });
    gridEl.addEventListener("drop", (e) => {
        gridEl.style.outline = "none";
        if (e.dataTransfer && e.dataTransfer.files.length) {
            e.preventDefault();
            uploadFileList(e.dataTransfer.files).catch((x) => toast(x.message, "error"));
        }
    });
    // Click on empty grid space (not a cell) clears the current selection.
    gridEl.addEventListener("click", (e) => {
        if (e.target === gridEl && STATE.selected.size) {
            STATE.selected.clear(); STATE.anchorName = null; rerender();
        }
    });

    attachContextMenu({
        rerender,
        newFolder: () => actNewFolder().catch((x) => toast(x.message, "error")),
        rename: () => actRename().catch((x) => toast(x.message, "error")),
        del: (perm) => actDelete(perm).catch((x) => toast(x.message, "error")),
        copy: doCopy,
        cut: doCut,
        paste: () => doPaste().catch((x) => toast(x.message, "error")),
        upload: () => document.getElementById("fm-file-input").click(),
    });

    const { roots } = await fetchRoots();
    STATE.roots = roots;
    settings.subscribe(SETTINGS_KEYS.ALLOW_HIDDEN, () => refresh().catch((e) => toast(e.message, "error")));
    settings.subscribe(SETTINGS_KEYS.SHOW_THUMBNAILS, rerender);
    settings.subscribe(SETTINGS_KEYS.GRID_DENSITY, rerender);
    settings.subscribe(SETTINGS_KEYS.THUMBNAIL_SIZE, rerender);
    settings.subscribe(SETTINGS_KEYS.SORT_FIELD, rerender);
    settings.subscribe(SETTINGS_KEYS.SORT_ORDER, rerender);
    settings.subscribe(SETTINGS_KEYS.SORT_FOLDERS_FIRST, rerender);
    renderTabs(roots);
    if (roots.length > 0) {
        const defaultRoot = settings.get(SETTINGS_KEYS.DEFAULT_ROOT);
        let preferredId = null;
        if (defaultRoot && defaultRoot !== "Last used") {
            preferredId = defaultRoot;
        } else {
            try { preferredId = localStorage.getItem("filemanaty.lastRoot"); } catch {}
        }
        const chosen = roots.find((r) => r.id === preferredId) || roots[0];
        await navigateTo(chosen.id, "");
    } else {
        document.getElementById("fm-grid").innerHTML = "<div style='color:var(--fm-text-muted)'>No roots configured.</div>";
    }
}

function renderTabs(roots) {
    const el = document.getElementById("fm-tabs");
    el.innerHTML = "";
    for (const r of roots) {
        const tab = document.createElement("button");
        tab.textContent = r.label;
        tab.dataset.rootId = r.id;
        tab.style.cssText = "background:var(--fm-hover);border:0;color:inherit;padding:4px 12px;border-radius:3px;cursor:pointer;";
        tab.addEventListener("click", () => navigateTo(r.id, ""));
        el.appendChild(tab);
    }
}

export async function navigateTo(rootId, relPath) {
    STATE.currentRoot = rootId;
    STATE.currentPath = relPath;
    STATE.selected.clear();
    STATE.anchorName = null;
    try { localStorage.setItem("filemanaty.lastRoot", rootId); } catch {}
    highlightTab();
    updateWritableUI();
    await refresh();   // refresh() re-renders the tree too
}

// Disable write actions in the toolbar when the current root is read-only.
// (The backend enforces this regardless; this just avoids dead-end clicks.)
function updateWritableUI() {
    const writable = currentRootWritable();
    const writeActs = new Set(["newfolder", "upload", "rename", "paste", "delete"]);
    document.querySelectorAll("#fm-toolbar .fm-tb").forEach((b) => {
        if (!writeActs.has(b.dataset.act)) return;
        b.disabled = !writable;
        b.style.opacity = writable ? "" : "0.4";
        b.style.cursor = writable ? "pointer" : "not-allowed";
        b.title = writable ? "" : "This root is read-only";
    });
}

async function onToolbarAction(act) {
    try {
        if (act === "newfolder") return await actNewFolder();
        if (act === "upload") { document.getElementById("fm-file-input").click(); return; }
        if (act === "rename") return await actRename();
        if (act === "copy") return doCopy();
        if (act === "cut") return doCut();
        if (act === "paste") return await doPaste();
        if (act === "delete") return await actDelete(false);
        if (act === "trash") return await trashView(STATE.currentRoot, () => refresh());
    } catch (e) {
        console.error("filemanaty action failed:", e);
        toast(e.message || "Action failed", "error");
    }
}

async function uploadFileList(files) {
    const list = [...files];
    toast(`Uploading ${list.length} file(s)…`);
    const data = await runWithConflicts((onConflict) =>
        apiUpload(STATE.currentRoot, STATE.currentPath, list, onConflict));
    if (data === null) return;  // cancelled at conflict
    await refresh();
    const failed = (data.results || []).filter((r) => r.status === "error");
    if (failed.length) toast(`${failed.length} upload(s) failed`, "error");
    else toast("Upload complete", "success");
}

export async function actNewFolder() {
    const name = await promptText("New folder name");
    if (!name) return;
    const err = validateName(name);
    if (err) { toast(err, "error"); return; }
    const r = await runWithConflicts((oc) => apiMkdir(STATE.currentRoot, STATE.currentPath, name, oc));
    if (r === null) return;  // cancelled at conflict dialog
    await refresh();
    toast("Folder created", "success");
}

export async function actRename() {
    if (STATE.selected.size !== 1) { toast("Select exactly one item to rename"); return; }
    const oldName = [...STATE.selected][0];
    const name = await promptText("Rename to", oldName);
    if (!name || name === oldName) return;
    const err = validateName(name);
    if (err) { toast(err, "error"); return; }
    const r = await runWithConflicts((oc) => apiRename(STATE.currentRoot, childPathOf(oldName), name, oc));
    if (r === null) return;  // cancelled at conflict dialog
    await refresh();
    toast("Renamed", "success");
}

export async function actDelete(permanent) {
    if (STATE.selected.size === 0) { toast("Nothing selected"); return; }
    const items = [...STATE.selected].map(childPathOf);
    const verb = permanent ? "Permanently delete" : "Move to Trash";
    const needConfirm = permanent
        ? settings.get(SETTINGS_KEYS.CONFIRM_ON_SHIFT_DELETE)
        : settings.get(SETTINGS_KEYS.CONFIRM_ON_DELETE);
    if (needConfirm) {
        const ok = await confirmDialog(`${verb} ${items.length} item(s)?`,
            permanent ? "This cannot be undone." : "You can restore from Trash later.",
            { danger: permanent });
        if (!ok) return;
    }
    await apiDel(STATE.currentRoot, items, permanent);
    await refresh();
    toast(permanent ? "Deleted" : "Moved to Trash", "success");
}

function highlightTab() {
    const tabs = document.querySelectorAll("#fm-tabs button");
    tabs.forEach((t) => {
        const active = t.dataset.rootId === STATE.currentRoot;
        t.style.background = active ? "var(--fm-accent)" : "var(--fm-hover)";
        t.style.color = active ? "var(--fm-on-accent)" : "inherit";
    });
}

export async function refresh() {
    if (!STATE.currentRoot) return;
    const includeHidden = settings.get(SETTINGS_KEYS.ALLOW_HIDDEN);
    const { entries, path } = await fetchList(STATE.currentRoot, STATE.currentPath, { includeHidden });
    STATE.entries = entries;
    // Drop any selected names that no longer exist after the refresh.
    STATE.selected = new Set([...STATE.selected].filter((n) => STATE.entries.some((e) => e.name === n)));
    renderBreadcrumb(path);
    renderGrid();
    renderPreview();
    renderTree().catch((e) => console.error("filemanaty tree render failed:", e));
}

function renderBreadcrumb(path) {
    const el = document.getElementById("fm-breadcrumb");
    const segs = (path || "").split("/").filter(Boolean);
    const rootLabel = STATE.roots.find((r) => r.id === STATE.currentRoot)?.label || STATE.currentRoot;
    const parts = [`<a href="#" data-bc="" style="color:inherit;text-decoration:none">${escapeHtml(rootLabel)}</a>`];
    let acc = "";
    for (const s of segs) {
        acc = acc ? `${acc}/${s}` : s;
        parts.push(`<span style="opacity:.5"> › </span><a href="#" data-bc="${escapeHtml(acc)}" style="color:inherit;text-decoration:none">${escapeHtml(s)}</a>`);
    }
    el.innerHTML = parts.join("");
    el.querySelectorAll("a[data-bc]").forEach((a) => {
        a.addEventListener("click", (ev) => {
            ev.preventDefault();
            navigateTo(STATE.currentRoot, a.dataset.bc);
        });
    });
}

function renderGrid() {
    const grid = document.getElementById("fm-grid");
    if (!grid) return;
    const showThumbs = settings.get(SETTINGS_KEYS.SHOW_THUMBNAILS);
    const thumbPx = { small: 100, medium: 140, large: 200 }[settings.get(SETTINGS_KEYS.THUMBNAIL_SIZE)] || 140;
    const densityGap = { compact: 4, normal: 8, comfortable: 14 }[settings.get(SETTINGS_KEYS.GRID_DENSITY)] || 8;
    grid.style.gridTemplateColumns = `repeat(auto-fill, minmax(${thumbPx}px, 1fr))`;
    // Explicit row height. A grid item's aspect-ratio does NOT feed the auto-row
    // track, so relying on it let tracks collapse to caption min-content (~30px)
    // while cells rendered full-height — rows overlapped. Fixed track = no overlap.
    grid.style.gridAutoRows = `${thumbPx}px`;
    grid.style.gap = `${densityGap}px`;
    grid.innerHTML = "";
    for (const e of sortedEntries()) {
        const cell = document.createElement("div");
        cell.dataset.name = e.name;
        cell.style.cssText = "position:relative;background:var(--fm-bg);border-radius:4px;cursor:pointer;display:flex;align-items:center;justify-content:center;overflow:hidden;";
        const childPath = STATE.currentPath ? `${STATE.currentPath}/${e.name}` : e.name;
        if (e.kind === "image" && showThumbs) {
            const img = document.createElement("img");
            img.loading = "lazy";
            img.src = thumbnailURL(STATE.currentRoot, childPath);
            img.style.cssText = "width:100%;height:100%;object-fit:cover;";
            img.onerror = () => { img.replaceWith(makeIcon("image")); };
            cell.appendChild(img);
        } else if (e.kind === "folder") {
            cell.appendChild(makeIcon("folder"));
        } else if (e.kind === "image") {
            cell.appendChild(makeIcon("image"));
        } else {
            cell.appendChild(makeIcon(e.kind));
        }
        const label = document.createElement("div");
        label.textContent = e.name;
        label.style.cssText = "position:absolute;bottom:0;left:0;right:0;padding:2px 6px;background:rgba(0,0,0,.7);color:#fff;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"; /* fixed light: sits on a dark scrim over the thumbnail */
        if (STATE.clipboard && STATE.clipboard.op === "cut"
            && STATE.clipboard.root === STATE.currentRoot
            && STATE.clipboard.paths.includes(childPath)) {
            cell.style.opacity = "0.45";
        }
        cell.appendChild(label);
        if (STATE.selected.has(e.name)) {
            cell.style.outline = "2px solid var(--fm-accent)";
            cell.style.outlineOffset = "2px";
        }
        cell.addEventListener("click", (ev) => onCellClick(e, ev));
        cell.addEventListener("dblclick", () => onCellDblClick(e));
        makeDraggable(cell, e.name);
        if (e.type === "dir") makeDropTarget(cell, STATE.currentRoot, childPath);
        grid.appendChild(cell);
    }
    const sc = document.getElementById("fm-selcount");
    if (sc) sc.textContent = STATE.selected.size ? `${STATE.selected.size} selected` : "";
}

function makeIcon(kind) {
    const d = document.createElement("div");
    d.textContent = kind === "folder" ? "📁" : kind === "image" ? "🖼"
        : kind === "video" ? "🎬" : kind === "audio" ? "🎵" : "📄";
    d.style.cssText = "font-size:34px;opacity:.65";
    return d;
}

function onCellClick(entry, ev) {
    clickSelect(entry, ev);
}

function onCellDblClick(entry) {
    if (entry.type === "dir") {
        const next = STATE.currentPath ? `${STATE.currentPath}/${entry.name}` : entry.name;
        navigateTo(STATE.currentRoot, next);
    }
}

// Guards against a slow metadata fetch painting over a newer selection: each
// renderPreview bumps the token; a resolved fetch only paints if it still matches.
let metaToken = 0;

function metaField(label, value) {
    const shown = value == null || value === "" ? "—" : escapeHtml(value);
    return `<div><span style="color:var(--fm-text-muted)">${label}:</span> ${shown}</div>`;
}

function metaCardHtml(data) {
    const f = data.fields;
    const loras = f.loras && f.loras.length ? f.loras.join(", ") : null;
    const btns = [];
    const btnStyle = "background:var(--fm-bg-elevated);color:var(--fm-text);border:1px solid var(--fm-border);padding:4px 10px;border-radius:3px;font-size:12px;cursor:pointer;";
    if (data.raw.workflow != null || data.raw.prompt != null) {
        btns.push(`<button data-action="load" style="${btnStyle}">Load on canvas</button>`);
        btns.push(`<button data-copy="json" style="${btnStyle}">Copy JSON</button>`);
    }
    return `
        <div style="border-top:1px solid var(--fm-border);margin-top:8px;padding-top:8px;font-size:12px;line-height:1.6;display:flex;flex-direction:column;gap:2px;">
            ${metaField("Positive", f.positive)}
            ${metaField("Negative", f.negative)}
            ${metaField("Seed", f.seed)}
            ${metaField("Model", f.model)}
            ${metaField("LoRAs", loras)}
            <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;">${btns.join("")}</div>
        </div>`;
}

function copyJSON(obj) {
    if (obj == null) return;
    const text = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
    // navigator.clipboard exists only in secure contexts (HTTPS/localhost). ComfyUI is
    // often served over plain HTTP on a LAN address, where it's undefined — fall back to
    // execCommand, which works inside this click handler's user gesture.
    if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text)
            .then(() => toast("Copied JSON"))
            .catch(() => legacyCopy(text));
        return;
    }
    legacyCopy(text);
}

function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { /* ok stays false */ }
    ta.remove();
    toast(ok ? "Copied JSON" : "Copy failed");
}

async function loadMetadata(root, path) {
    const token = ++metaToken;
    const muted = (msg) => `<div style="color:var(--fm-text-muted);font-size:12px">${msg}</div>`;
    let data;
    try {
        data = await fetchMetadata(root, path);
    } catch {
        paintMeta(token, muted("Metadata unavailable."));
        return;
    }
    if (!data.raw) {
        paintMeta(token, muted("No embedded workflow metadata."));
        return;
    }
    paintMeta(token, metaCardHtml(data));
    const el = document.getElementById("fm-meta");
    if (!el || token !== metaToken) return;
    // Prefer the full UI workflow (round-trips to canvas); fall back to the API
    // prompt for files that embed only that.
    el.querySelector("[data-copy=json]")?.addEventListener("click", () => copyJSON(data.raw.workflow ?? data.raw.prompt));
    el.querySelector("[data-action=load]")?.addEventListener("click", () => loadWorkflowOnCanvas(root, path));
}

// Hand the raw file to ComfyUI's own load-from-file path so it extracts and loads
// the embedded workflow — works for any format/embedding ComfyUI supports.
async function loadWorkflowOnCanvas(root, path) {
    try {
        const resp = await fetch(downloadURL(root, path));
        if (!resp.ok) throw new Error(`download failed (${resp.status})`);
        const blob = await resp.blob();
        const name = path.split("/").pop();
        await app.handleFile(new File([blob], name, { type: blob.type }));
        closeOverlay();
        toast("Loaded workflow");
    } catch {
        toast("Could not load workflow");
    }
}

function paintMeta(token, html) {
    if (token !== metaToken) return;  // stale fetch — selection moved on
    const el = document.getElementById("fm-meta");
    if (el) el.innerHTML = html;
}

function renderPreview() {
    const el = document.getElementById("fm-preview");
    const onlyName = STATE.selected.size === 1 ? [...STATE.selected][0] : null;
    const sel = onlyName ? STATE.entries.find((e) => e.name === onlyName) : null;
    if (!sel) {
        el.innerHTML = "<div style='color:var(--fm-text-muted)'>Select a file.</div>";
        return;
    }
    const childPath = STATE.currentPath ? `${STATE.currentPath}/${sel.name}` : sel.name;
    const sizeKb = Math.round(sel.size / 1024);
    const dateStr = new Date(sel.mtime * 1000).toLocaleString();
    if (sel.kind === "image") {
        el.innerHTML = `
            <div style="flex:1;display:flex;align-items:center;justify-content:center;background:var(--fm-bg);border-radius:4px;min-height:0;">
                <img src="${previewURL(STATE.currentRoot, childPath)}" style="max-width:100%;max-height:100%;object-fit:contain;">
            </div>
            <div style="font-size:12px;line-height:1.6;">
                <div><strong>${escapeHtml(sel.name)}</strong></div>
                <div style="color:var(--fm-text-muted)">${sizeKb} KB · modified ${escapeHtml(dateStr)}</div>
            </div>
            <div style="display:flex;gap:6px;">
                <a href="${downloadURL(STATE.currentRoot, childPath)}" style="background:var(--fm-accent);color:var(--fm-on-accent);padding:5px 12px;border-radius:3px;text-decoration:none;font-size:12px;">Download</a>
            </div>
            <div id="fm-meta" style="color:var(--fm-text-muted);font-size:12px;">Loading metadata…</div>
        `;
        loadMetadata(STATE.currentRoot, childPath);
    } else if (sel.kind === "video") {
        el.innerHTML = `
            <div style="flex:1;display:flex;align-items:center;justify-content:center;background:var(--fm-bg);border-radius:4px;min-height:0;">
                <video controls preload="metadata" src="${previewURL(STATE.currentRoot, childPath)}" style="max-width:100%;max-height:100%;"></video>
            </div>
            <div style="font-size:12px;line-height:1.6;">
                <div><strong>${escapeHtml(sel.name)}</strong></div>
                <div style="color:var(--fm-text-muted)">${sizeKb} KB · modified ${escapeHtml(dateStr)}</div>
            </div>
            <div style="display:flex;gap:6px;">
                <a href="${downloadURL(STATE.currentRoot, childPath)}" style="background:var(--fm-accent);color:var(--fm-on-accent);padding:5px 12px;border-radius:3px;text-decoration:none;font-size:12px;">Download</a>
            </div>
            <div id="fm-meta" style="color:var(--fm-text-muted);font-size:12px;">Loading metadata…</div>
        `;
        loadMetadata(STATE.currentRoot, childPath);
    } else if (sel.kind === "audio") {
        el.innerHTML = `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;background:var(--fm-bg);border-radius:4px;min-height:0;gap:16px;">
                <div style="font-size:54px;opacity:.45">🎵</div>
                <audio controls src="${previewURL(STATE.currentRoot, childPath)}" style="width:90%;"></audio>
            </div>
            <div style="font-size:12px;line-height:1.6;">
                <div><strong>${escapeHtml(sel.name)}</strong></div>
                <div style="color:var(--fm-text-muted)">${sizeKb} KB · modified ${escapeHtml(dateStr)}</div>
            </div>
            <div style="display:flex;gap:6px;">
                <a href="${downloadURL(STATE.currentRoot, childPath)}" style="background:var(--fm-accent);color:var(--fm-on-accent);padding:5px 12px;border-radius:3px;text-decoration:none;font-size:12px;">Download</a>
            </div>
        `;
    } else if (sel.kind === "folder") {
        el.innerHTML = `<div><strong>${escapeHtml(sel.name)}</strong> (folder)</div><div style="color:var(--fm-text-muted);font-size:12px">Double-click to open.</div>`;
    } else {
        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;flex:1;font-size:60px;opacity:.5">📄</div>
            <div style="font-size:12px;line-height:1.6;">
                <div><strong>${escapeHtml(sel.name)}</strong></div>
                <div style="color:var(--fm-text-muted)">${sizeKb} KB · modified ${escapeHtml(dateStr)}</div>
            </div>
            <div style="display:flex;gap:6px;">
                <a href="${downloadURL(STATE.currentRoot, childPath)}" style="background:var(--fm-accent);color:var(--fm-on-accent);padding:5px 12px;border-radius:3px;text-decoration:none;font-size:12px;">Download</a>
            </div>
        `;
    }
}

export function sortedEntries() {
    const field = settings.get(SETTINGS_KEYS.SORT_FIELD);
    const order = settings.get(SETTINGS_KEYS.SORT_ORDER);
    const foldersFirst = settings.get(SETTINGS_KEYS.SORT_FOLDERS_FIRST);
    const dir = order === "desc" ? -1 : 1;

    const cmpByField = (a, b) => {
        if (field === "size") return (a.size - b.size) * dir;
        if (field === "mtime") return (a.mtime - b.mtime) * dir;
        if (field === "type") return a.kind.localeCompare(b.kind) * dir || a.name.localeCompare(b.name);
        return a.name.localeCompare(b.name) * dir;
    };

    return [...STATE.entries].sort((a, b) => {
        if (foldersFirst && a.type !== b.type) return a.type === "dir" ? -1 : 1;
        return cmpByField(a, b);
    });
}

function computeGridColumns() {
    const grid = document.getElementById("fm-grid");
    if (!grid) return 1;
    const style = window.getComputedStyle(grid);
    return style.gridTemplateColumns.split(" ").length || 1;
}

// Inject the manatee icon CSS at load so the action-bar button renders with it.
injectBrandStyles();

app.registerExtension({
    name: "filemanaty.viewer",
    commands: [
        { id: "filemanaty.open", label: "Open File Manager", function: openOverlay },
    ],
    keybindings: [
        { commandId: "filemanaty.open", combo: { key: "f", ctrl: true, shift: true } },
    ],
    actionBarButtons: [
        { icon: "fm-icon-manatee", label: "Files", tooltip: "Open file manager", onClick: openOverlay },
    ],
    settings: await (async () => {
        // Fetch root ids so the DefaultRoot combo lists them.
        try {
            const { roots } = await fetchRoots();
            return buildSettingsDefinitions(roots.map((r) => r.id));
        } catch (e) {
            console.warn("filemanaty: failed to fetch roots for settings combo:", e);
            return buildSettingsDefinitions([]);
        }
    })(),
});
