import { downloadURL } from "./api.js";
import { STATE, childPathOf } from "./filemanaty.js";

let openMenu = null;
function destroy() { if (openMenu) { openMenu.remove(); openMenu = null; } }
document.addEventListener("click", destroy);

// items: [{ label, danger?, onClick }] | { separator: true }
function show(x, y, items) {
    destroy();
    const menu = document.createElement("div");
    menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:9700;background:var(--fm-bg-elevated);border:1px solid var(--fm-border);border-radius:6px;padding:4px 0;min-width:160px;box-shadow:0 6px 18px rgba(0,0,0,.5);font-size:13px;color:var(--fm-text)`;
    for (const it of items) {
        if (it.separator) {
            const sep = document.createElement("div");
            sep.style.cssText = "height:1px;background:var(--fm-border);margin:4px 0";
            menu.appendChild(sep);
            continue;
        }
        const row = document.createElement("div");
        row.textContent = it.label;
        row.style.cssText = `padding:5px 14px;cursor:pointer;${it.danger ? "color:var(--fm-danger)" : ""}`;
        row.onmouseenter = () => (row.style.background = "var(--fm-accent-soft)");
        row.onmouseleave = () => (row.style.background = "transparent");
        row.onclick = () => { destroy(); it.onClick(); };
        menu.appendChild(row);
    }
    document.body.appendChild(menu);
    openMenu = menu;
}

// actions: a bundle of handlers passed from filemanaty.js to avoid eval-time import cycles
export function attachContextMenu(actions) {
    const grid = document.getElementById("fm-grid");
    grid.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        const cell = e.target.closest("[data-name]");
        if (cell) {
            const name = cell.dataset.name;
            if (!STATE.selected.has(name)) { STATE.selected = new Set([name]); STATE.anchorName = name; actions.rerender(); }
            const entry = STATE.entries.find((x) => x.name === name);
            const items = [
                { label: "Rename", onClick: actions.rename },
                { label: "Copy", onClick: actions.copy },
                { label: "Cut", onClick: actions.cut },
                { separator: true },
            ];
            if (entry && entry.type === "file") {
                items.push({ label: "Download", onClick: () => window.open(downloadURL(STATE.currentRoot, childPathOf(name)), "_blank") });
                items.push({ separator: true });
            }
            items.push({ label: "Delete → Trash", danger: true, onClick: () => actions.del(false) });
            show(e.clientX, e.clientY, items);
        } else {
            show(e.clientX, e.clientY, [
                { label: "New Folder", onClick: actions.newFolder },
                { label: "Upload…", onClick: actions.upload },
                { label: "Paste", onClick: actions.paste },
            ]);
        }
    });
}
