import { fetchList } from "./api.js";
import { STATE, navigateTo } from "./filemanaty.js";
import { makeDropTarget } from "./dnd.js";

// Expanded folder keys ("root path"), module-global so they survive re-renders.
const expanded = new Set();
function key(root, path) { return `${root} ${path}`; }

export async function renderTree() {
    const host = document.getElementById("fm-tree");
    if (!host) return;
    host.innerHTML = "";
    for (const r of STATE.roots) {
        await renderNode(host, r.label, r.id, "", 0, true);
    }
}

// Render one node into `container`; if it is in `expanded`, fetch and render its
// subfolders recursively (so deep expansion state is preserved across rebuilds).
async function renderNode(container, label, root, path, depth, isRoot) {
    const isOpen = expanded.has(key(root, path));
    const active = STATE.currentRoot === root && STATE.currentPath === path;
    const row = document.createElement("div");
    row.style.cssText = `display:flex;align-items:center;padding:3px 4px 3px ${6 + depth * 14}px;cursor:pointer;border-radius:4px;white-space:nowrap;overflow:hidden;${active ? "background:rgba(120,160,255,.25)" : ""}`;
    row.dataset.root = root;
    row.dataset.path = path;

    const caret = document.createElement("span");
    caret.textContent = "▸";
    caret.style.cssText = `display:inline-block;width:14px;flex:none;opacity:.7;transform:rotate(${isOpen ? 90 : 0}deg);`;
    caret.onclick = (e) => {
        e.stopPropagation();               // caret toggles expansion only
        if (expanded.has(key(root, path))) expanded.delete(key(root, path));
        else expanded.add(key(root, path));
        renderTree();
    };
    row.appendChild(caret);

    const labelSpan = document.createElement("span");
    labelSpan.style.cssText = "overflow:hidden;text-overflow:ellipsis;";
    labelSpan.textContent = (isRoot ? "🗀 " : "") + label;
    row.appendChild(labelSpan);

    row.onclick = (e) => {                  // row navigates AND opens the folder
        e.stopPropagation();
        expanded.add(key(root, path));
        navigateTo(root, path);             // triggers renderTree() which reflects `expanded`
    };
    makeDropTarget(row, root, path);
    container.appendChild(row);

    if (isOpen) {
        const childBox = document.createElement("div");
        container.appendChild(childBox);
        try {
            const { entries } = await fetchList(root, path);
            const dirs = entries.filter((e) => e.type === "dir").sort((a, b) => a.name.localeCompare(b.name));
            for (const d of dirs) {
                const childPath = path ? `${path}/${d.name}` : d.name;
                await renderNode(childBox, d.name, root, childPath, depth + 1, false);
            }
        } catch (e) {
            console.error("filemanaty tree expand failed:", e);
        }
    }
}
