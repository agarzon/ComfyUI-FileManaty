import { fetchList } from "./api.js";
import { STATE, navigateTo, syncFavoriteButton } from "./filemanaty.js";
import { makeDropTarget } from "./dnd.js";
import { load as loadFavorites, save as saveFavorites, toggleIn } from "./favorites.js";

// Expanded folder keys ("root path"), module-global so they survive re-renders.
const expanded = new Set();
function key(root, path) { return `${root} ${path}`; }

export async function renderTree() {
    const host = document.getElementById("fm-tree");
    if (!host) return;
    host.innerHTML = "";
    renderFavorites(host);
    for (const r of STATE.roots) {
        await renderNode(host, r.label, r.id, "", 0, true);
    }
}

const rootLabel = (id) => STATE.roots.find((r) => r.id === id)?.label || id;

// Favorites from a root that is no longer configured are hidden rather than
// dropped: the config may name it again tomorrow.
function renderFavorites(host) {
    const favs = loadFavorites().filter((f) => STATE.roots.some((r) => r.id === f.root));
    if (!favs.length) return;
    const box = document.createElement("div");
    box.style.cssText = "margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--fm-border)";
    const head = document.createElement("div");
    head.textContent = "★ Favorites";
    head.style.cssText = "padding:2px 4px 5px 6px;font-size:11px;color:var(--fm-text-muted)";
    box.appendChild(head);
    for (const f of favs) box.appendChild(favoriteRow(f));
    host.appendChild(box);
}

function favoriteRow(f) {
    const active = STATE.currentRoot === f.root && STATE.currentPath === f.path;
    const row = document.createElement("div");
    row.style.cssText = `display:flex;align-items:center;gap:4px;padding:3px 4px 3px 6px;cursor:pointer;border-radius:4px;white-space:nowrap;overflow:hidden;${active ? "background:rgba(120,160,255,.25)" : ""}`;

    const label = document.createElement("span");
    label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;";
    label.textContent = "★ " + (f.path ? f.path.split("/").pop() : rootLabel(f.root));
    row.title = f.path ? `${rootLabel(f.root)} / ${f.path}` : rootLabel(f.root);
    row.appendChild(label);

    const remove = document.createElement("button");
    remove.textContent = "✕";
    remove.title = "Remove from favorites";
    remove.setAttribute("aria-label", `Remove ${row.title} from favorites`);
    remove.style.cssText = "background:none;border:0;color:var(--fm-text-muted);cursor:pointer;padding:0 2px;line-height:1;font-size:11px";
    remove.onclick = (e) => {
        e.stopPropagation();
        saveFavorites(toggleIn(loadFavorites(), f.root, f.path));
        syncFavoriteButton();
        renderTree();
    };
    row.appendChild(remove);

    row.onclick = () => navigateTo(f.root, f.path);
    return row;
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
