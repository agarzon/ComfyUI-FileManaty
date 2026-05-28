import { app } from "../../scripts/app.js";
import { fetchRoots, fetchList, thumbnailURL, previewURL, downloadURL } from "./api.js";

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

const STATE = {
    overlay: null,
    open: false,
    currentRoot: null,
    currentPath: "",
    entries: [],
    selectedName: null,
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
        <div id="fm-toolbar" style="display:flex;align-items:center;gap:8px;padding:6px 14px;border-bottom:1px solid #2a2a2a;font-size:12px;color:#aaa;">
            <span id="fm-breadcrumb"></span>
            <span style="flex:1"></span>
            <button id="fm-refresh" style="background:#2a2a2a;border:0;color:inherit;padding:3px 10px;border-radius:3px;cursor:pointer">Refresh</button>
        </div>
        <div id="fm-body" style="flex:1;display:grid;grid-template-columns:1fr 38%;min-height:0;">
            <div id="fm-grid" style="overflow:auto;padding:10px;display:grid;gap:8px;align-content:start;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));"></div>
            <div id="fm-preview" style="border-left:1px solid #2a2a2a;padding:14px;display:flex;flex-direction:column;gap:10px;background:#181818;"></div>
        </div>
    `;
    return root;
}

async function initOverlay() {
    document.getElementById("fm-close").addEventListener("click", closeOverlay);
    document.addEventListener("keydown", (e) => {
        if (!STATE.open) return;
        if (e.key === "Escape") { closeOverlay(); return; }

        const grid = sortedEntries();
        const idx = grid.findIndex((entry) => entry.name === STATE.selectedName);
        const cols = computeGridColumns();
        if (e.key === "ArrowRight" && idx < grid.length - 1) { STATE.selectedName = grid[idx + 1].name; e.preventDefault(); }
        else if (e.key === "ArrowLeft" && idx > 0) { STATE.selectedName = grid[idx - 1].name; e.preventDefault(); }
        else if (e.key === "ArrowDown" && idx + cols < grid.length) { STATE.selectedName = grid[idx + cols].name; e.preventDefault(); }
        else if (e.key === "ArrowUp" && idx - cols >= 0) { STATE.selectedName = grid[idx - cols].name; e.preventDefault(); }
        else if (e.key === "Enter") {
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
        } else {
            return;
        }
        renderGrid();
        renderPreview();
    });
    document.getElementById("fm-refresh").addEventListener("click", () => refresh());

    const { roots } = await fetchRoots();
    STATE.roots = roots;
    renderTabs(roots);
    if (roots.length > 0) {
        let preferred = null;
        try { preferred = localStorage.getItem("filemanaty.lastRoot"); } catch {}
        const chosen = roots.find((r) => r.id === preferred) || roots[0];
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

async function navigateTo(rootId, relPath) {
    STATE.currentRoot = rootId;
    STATE.currentPath = relPath;
    STATE.selectedName = null;
    try { localStorage.setItem("filemanaty.lastRoot", rootId); } catch {}
    highlightTab();
    await refresh();
}

function highlightTab() {
    const tabs = document.querySelectorAll("#fm-tabs button");
    tabs.forEach((t) => {
        const active = t.dataset.rootId === STATE.currentRoot;
        t.style.background = active ? "#0a84ff" : "#2a2a2a";
        t.style.color = active ? "white" : "inherit";
    });
}

async function refresh() {
    if (!STATE.currentRoot) return;
    const { entries, path } = await fetchList(STATE.currentRoot, STATE.currentPath);
    STATE.entries = entries;
    renderBreadcrumb(path);
    renderGrid();
    renderPreview();
}

function renderBreadcrumb(path) {
    const el = document.getElementById("fm-breadcrumb");
    const segs = (path || "").split("/").filter(Boolean);
    const parts = [`<a href="#" data-bc="" style="color:inherit;text-decoration:none">${escapeHtml(STATE.currentRoot)}</a>`];
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
    grid.innerHTML = "";
    const sorted = [...STATE.entries].sort((a, b) => {
        if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
        return a.name.localeCompare(b.name);
    });
    for (const e of sorted) {
        const cell = document.createElement("div");
        cell.dataset.name = e.name;
        cell.style.cssText = "position:relative;aspect-ratio:1;background:#222;border-radius:4px;cursor:pointer;display:flex;align-items:center;justify-content:center;overflow:hidden;";
        if (e.kind === "image") {
            const img = document.createElement("img");
            img.loading = "lazy";
            const childPath = STATE.currentPath ? `${STATE.currentPath}/${e.name}` : e.name;
            img.src = thumbnailURL(STATE.currentRoot, childPath);
            img.style.cssText = "width:100%;height:100%;object-fit:cover;";
            img.onerror = () => { img.replaceWith(makeIcon("image")); };
            cell.appendChild(img);
        } else if (e.kind === "folder") {
            cell.appendChild(makeIcon("folder"));
        } else {
            cell.appendChild(makeIcon("file"));
        }
        const label = document.createElement("div");
        label.textContent = e.name;
        label.style.cssText = "position:absolute;bottom:0;left:0;right:0;padding:2px 6px;background:rgba(0,0,0,.7);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
        cell.appendChild(label);
        if (e.name === STATE.selectedName) {
            cell.style.outline = "2px solid #0a84ff";
            cell.style.outlineOffset = "2px";
        }
        cell.addEventListener("click", () => onCellClick(e));
        cell.addEventListener("dblclick", () => onCellDblClick(e));
        grid.appendChild(cell);
    }
}

function makeIcon(kind) {
    const d = document.createElement("div");
    d.textContent = kind === "folder" ? "📁" : kind === "image" ? "🖼" : "📄";
    d.style.cssText = "font-size:34px;opacity:.65";
    return d;
}

function onCellClick(entry) {
    STATE.selectedName = entry.name;
    renderGrid();
    renderPreview();
}

function onCellDblClick(entry) {
    if (entry.type === "dir") {
        const next = STATE.currentPath ? `${STATE.currentPath}/${entry.name}` : entry.name;
        navigateTo(STATE.currentRoot, next);
    }
}

function renderPreview() {
    const el = document.getElementById("fm-preview");
    const sel = STATE.entries.find((e) => e.name === STATE.selectedName);
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

function sortedEntries() {
    return [...STATE.entries].sort((a, b) => {
        if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
        return a.name.localeCompare(b.name);
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
