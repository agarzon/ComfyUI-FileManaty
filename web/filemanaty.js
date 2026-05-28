import { app } from "../../scripts/app.js";
import { fetchRoots, fetchList, thumbnailURL, previewURL, downloadURL, mkdir as apiMkdir, rename as apiRename, del as apiDel, uploadFiles as apiUpload } from "./api.js";
import { doCopy, doCut, doPaste, runWithConflicts } from "./clipboard.js";
import { clickSelect, selectAll } from "./selection.js";
import { promptText, confirmDialog, toast, trashView } from "./dialogs.js";
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
        "background:var(--p-content-background,#111)",
        "color:var(--p-text-color,#ddd)",
        "display:flex",
        "flex-direction:column",
    ].join(";");
    root.innerHTML = `
        <div id="fm-header" style="display:flex;justify-content:space-between;align-items:center;padding:8px 14px;border-bottom:1px solid #333;background:#1a1a1a;">
            <strong>Files <span id="fm-bc" style="opacity:.7;font-weight:normal;margin-left:8px"></span></strong>
            <button id="fm-close" style="background:none;border:0;color:inherit;font-size:18px;cursor:pointer">✕</button>
        </div>
        <div id="fm-tabs" style="display:flex;gap:4px;padding:6px 14px;border-bottom:1px solid #333;background:#1e1e1e;"></div>
        <input id="fm-file-input" type="file" multiple style="display:none">
        <div id="fm-toolbar" style="display:flex;align-items:center;gap:6px;padding:6px 14px;border-bottom:1px solid #2a2a2a;font-size:12px;color:#aaa;">
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
            <button id="fm-refresh" class="fm-tb">Refresh</button>
        </div>
        <div id="fm-body" style="flex:1;display:grid;grid-template-columns:200px 1fr 34%;min-height:0;">
            <div id="fm-tree" style="overflow:auto;padding:8px;border-right:1px solid #2a2a2a;background:#161616;font-size:13px;"></div>
            <div id="fm-grid" style="overflow:auto;padding:10px;display:grid;gap:8px;align-content:start;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));"></div>
            <div id="fm-preview" style="border-left:1px solid #2a2a2a;padding:14px;display:flex;flex-direction:column;gap:10px;background:#181818;"></div>
        </div>
    `;
    const style = document.createElement("style");
    style.textContent = `#filemanaty-overlay .fm-tb{background:#2a2a2a;border:0;color:inherit;padding:4px 10px;border-radius:3px;cursor:pointer;font-size:12px}
#filemanaty-overlay .fm-tb:hover{background:#3a3a3a}
#filemanaty-overlay .fm-tb.danger{color:#ff9a9a}`;
    root.appendChild(style);
    return root;
}

async function initOverlay() {
    document.getElementById("fm-close").addEventListener("click", closeOverlay);
    document.addEventListener("keydown", (e) => {
        if (!STATE.open) return;
        if (e.key === "Escape") { closeOverlay(); return; }
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
            gridEl.style.outline = "2px dashed #0a84ff";
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
        document.getElementById("fm-grid").innerHTML = "<div style='color:#888'>No roots configured.</div>";
    }
}

function renderTabs(roots) {
    const el = document.getElementById("fm-tabs");
    el.innerHTML = "";
    for (const r of roots) {
        const tab = document.createElement("button");
        tab.textContent = r.label;
        tab.dataset.rootId = r.id;
        tab.style.cssText = "background:#2a2a2a;border:0;color:inherit;padding:4px 12px;border-radius:3px;cursor:pointer;";
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
    renderTree().catch((e) => console.error("filemanaty tree render failed:", e));
    await refresh();
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
        t.style.background = active ? "#0a84ff" : "#2a2a2a";
        t.style.color = active ? "white" : "inherit";
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
    grid.style.gap = `${densityGap}px`;
    grid.innerHTML = "";
    for (const e of sortedEntries()) {
        const cell = document.createElement("div");
        cell.dataset.name = e.name;
        cell.style.cssText = "position:relative;aspect-ratio:1;background:#222;border-radius:4px;cursor:pointer;display:flex;align-items:center;justify-content:center;overflow:hidden;";
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
            cell.appendChild(makeIcon("file"));
        }
        const label = document.createElement("div");
        label.textContent = e.name;
        label.style.cssText = "position:absolute;bottom:0;left:0;right:0;padding:2px 6px;background:rgba(0,0,0,.7);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
        if (STATE.clipboard && STATE.clipboard.op === "cut"
            && STATE.clipboard.root === STATE.currentRoot
            && STATE.clipboard.paths.includes(childPathOf(e.name))) {
            cell.style.opacity = "0.45";
        }
        cell.appendChild(label);
        if (STATE.selected.has(e.name)) {
            cell.style.outline = "2px solid #0a84ff";
            cell.style.outlineOffset = "2px";
        }
        cell.addEventListener("click", (ev) => onCellClick(e, ev));
        cell.addEventListener("dblclick", () => onCellDblClick(e));
        makeDraggable(cell, e.name);
        if (e.type === "dir") makeDropTarget(cell, STATE.currentRoot, childPathOf(e.name));
        grid.appendChild(cell);
    }
    const sc = document.getElementById("fm-selcount");
    if (sc) sc.textContent = STATE.selected.size ? `${STATE.selected.size} selected` : "";
}

function makeIcon(kind) {
    const d = document.createElement("div");
    d.textContent = kind === "folder" ? "📁" : kind === "image" ? "🖼" : "📄";
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

function renderPreview() {
    const el = document.getElementById("fm-preview");
    const onlyName = STATE.selected.size === 1 ? [...STATE.selected][0] : null;
    const sel = onlyName ? STATE.entries.find((e) => e.name === onlyName) : null;
    if (!sel) {
        el.innerHTML = "<div style='color:#666'>Select a file.</div>";
        return;
    }
    const childPath = STATE.currentPath ? `${STATE.currentPath}/${sel.name}` : sel.name;
    const sizeKb = Math.round(sel.size / 1024);
    const dateStr = new Date(sel.mtime * 1000).toLocaleString();
    if (sel.kind === "image") {
        el.innerHTML = `
            <div style="flex:1;display:flex;align-items:center;justify-content:center;background:#0e0e0e;border-radius:4px;min-height:0;">
                <img src="${previewURL(STATE.currentRoot, childPath)}" style="max-width:100%;max-height:100%;object-fit:contain;">
            </div>
            <div style="font-size:12px;line-height:1.6;">
                <div><strong>${escapeHtml(sel.name)}</strong></div>
                <div style="color:#aaa">${sizeKb} KB · modified ${escapeHtml(dateStr)}</div>
            </div>
            <div style="display:flex;gap:6px;">
                <a href="${downloadURL(STATE.currentRoot, childPath)}" style="background:#0a84ff;color:white;padding:5px 12px;border-radius:3px;text-decoration:none;font-size:12px;">Download</a>
            </div>
        `;
    } else if (sel.kind === "folder") {
        el.innerHTML = `<div><strong>${escapeHtml(sel.name)}</strong> (folder)</div><div style="color:#aaa;font-size:12px">Double-click to open.</div>`;
    } else {
        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;flex:1;font-size:60px;opacity:.5">📄</div>
            <div style="font-size:12px;line-height:1.6;">
                <div><strong>${escapeHtml(sel.name)}</strong></div>
                <div style="color:#aaa">${sizeKb} KB · modified ${escapeHtml(dateStr)}</div>
            </div>
            <div style="display:flex;gap:6px;">
                <a href="${downloadURL(STATE.currentRoot, childPath)}" style="background:#0a84ff;color:white;padding:5px 12px;border-radius:3px;text-decoration:none;font-size:12px;">Download</a>
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

app.registerExtension({
    name: "filemanaty.viewer",
    commands: [
        { id: "filemanaty.open", label: "Open File Manager", function: openOverlay },
    ],
    keybindings: [
        { commandId: "filemanaty.open", combo: { key: "f", ctrl: true, shift: true } },
    ],
    actionBarButtons: [
        { icon: "pi pi-folder", label: "Files", tooltip: "Open file manager", onClick: openOverlay },
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
    async setup(app) {
        app.extensionManager.registerSidebarTab({
            id: "filemanaty",
            title: "Files",
            icon: "pi pi-folder",
            type: "custom",
            render: (container) => {
                container.innerHTML = `
                    <div style="padding:10px;">
                        <button id="fm-sidebar-open" style="width:100%;padding:8px;background:#0a84ff;color:white;border:0;border-radius:4px;cursor:pointer;">
                            Open File Manager
                        </button>
                    </div>
                `;
                container.querySelector("#fm-sidebar-open").addEventListener("click", openOverlay);
            },
        });
    },
});
