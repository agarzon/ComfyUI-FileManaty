// The basket: a selection that outlives navigation. Clicking still selects
// within one folder and still clears when you leave it — items only enter the
// basket by an explicit "Add", and everything in it is listed, because acting on
// items you cannot see is how people delete the wrong file.
//
// Paths are root-relative and the basket is pinned to the root they came from,
// which is what /copy, /move and /delete already accept. The destination is free:
// the backend takes src_root and dst_root separately, so the basket pastes into
// any root.

import { STATE, selectedPaths, currentRootWritable, refresh, actDelete, escapeHtml } from "./filemanaty.js";
import { copy as apiCopy, move as apiMove } from "./api.js";
import { runWithConflicts } from "./clipboard.js";
import { toast } from "./dialogs.js";

const rootLabel = (id) => STATE.roots.find((r) => r.id === id)?.label || id;

export function addSelection() {
    if (!STATE.selected.size) { toast("Nothing selected"); return; }
    const b = STATE.basket;
    if (b.paths.length && b.root !== STATE.currentRoot) {
        toast(`The basket holds items from ${rootLabel(b.root)}. Empty it to collect from another root.`, "error");
        return;
    }
    b.root = STATE.currentRoot;
    const known = new Set(b.paths);
    const added = selectedPaths().filter((p) => !known.has(p));
    b.paths.push(...added);
    toast(added.length ? `Added ${added.length} item(s) to the basket` : "Already in the basket");
    renderBasket();
}

export function clearBasket() {
    STATE.basket = { root: null, paths: [] };
    renderBasket();
}

function removeOne(path) {
    const b = STATE.basket;
    b.paths = b.paths.filter((p) => p !== path);
    if (!b.paths.length) b.root = null;
    renderBasket();
}

// Copy or move the whole basket into the folder on screen. Same conflict flow as
// Paste, since it is the same request.
async function pasteBasket(move) {
    const b = STATE.basket;
    if (!b.paths.length) return;
    const fn = move ? apiMove : apiCopy;
    const result = await runWithConflicts((onConflict) =>
        fn(b.root, b.paths, STATE.currentRoot, STATE.currentPath, onConflict));
    if (result === null) return;   // cancelled at conflict dialog
    if (move) clearBasket();       // the sources it points at are gone
    await refresh();
    toast(move ? "Moved" : "Copied", "success");
}

async function deleteBasket() {
    const b = STATE.basket;
    if (await actDelete(false, { root: b.root, paths: b.paths })) clearBasket();
}

export function renderBasket() {
    const el = document.getElementById("fm-basket");
    if (!el) return;
    const b = STATE.basket;
    if (!b.paths.length) { el.style.display = "none"; el.innerHTML = ""; return; }

    // Move and Delete write to the basket's own root; Copy only reads from it.
    const srcWritable = STATE.roots.find((r) => r.id === b.root)?.writable !== false;
    const dstWritable = currentRootWritable();
    el.style.display = "block";
    el.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;padding:6px 14px">
            <span style="font-weight:600">🧺 Basket</span>
            <span style="color:var(--fm-text-muted)">${b.paths.length} item(s) from ${escapeHtml(rootLabel(b.root))}</span>
            <span style="flex:1"></span>
            <button class="fm-tb" data-fm-b="copy">⧉ Copy here</button>
            <button class="fm-tb" data-fm-b="move">➜ Move here</button>
            <button class="fm-tb danger" data-fm-b="delete">🗑 Delete</button>
            <button class="fm-tb" data-fm-b="clear">Empty</button>
        </div>
        <div data-fm-b-items style="display:flex;flex-wrap:wrap;gap:4px;padding:0 14px 8px;max-height:76px;overflow:auto"></div>`;

    const dis = (sel, ok, why) => {
        const btn = el.querySelector(sel);
        btn.disabled = !ok;
        btn.style.opacity = ok ? "" : "0.4";
        btn.style.cursor = ok ? "pointer" : "not-allowed";
        btn.title = ok ? "" : why;
    };
    dis('[data-fm-b="copy"]', dstWritable, "This root is read-only");
    dis('[data-fm-b="move"]', dstWritable && srcWritable, "A move deletes the source, so both roots must be writable");
    dis('[data-fm-b="delete"]', srcWritable, `${rootLabel(b.root)} is read-only`);

    const items = el.querySelector("[data-fm-b-items]");
    for (const p of b.paths) {
        const chip = document.createElement("span");
        chip.style.cssText = "display:inline-flex;align-items:center;gap:4px;max-width:220px;background:var(--fm-hover);border-radius:3px;padding:2px 4px 2px 8px;font-size:11px";
        chip.innerHTML = `<span data-fm-b-path style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
            <button title="Remove" aria-label="Remove from basket" style="background:none;border:0;color:var(--fm-text-muted);cursor:pointer;padding:0 2px;line-height:1">✕</button>`;
        const nameEl = chip.querySelector("[data-fm-b-path]");
        nameEl.textContent = p;
        nameEl.title = p;
        chip.querySelector("button").onclick = () => removeOne(p);
        items.appendChild(chip);
    }

    // Paths in the basket can go stale — the folder they name may have been
    // renamed or deleted from another tab — so these requests do fail.
    const guard = (fn) => () => fn().catch((e) => toast(e.message || "Action failed", "error"));
    el.querySelector('[data-fm-b="copy"]').onclick = guard(() => pasteBasket(false));
    el.querySelector('[data-fm-b="move"]').onclick = guard(() => pasteBasket(true));
    el.querySelector('[data-fm-b="delete"]').onclick = guard(deleteBasket);
    el.querySelector('[data-fm-b="clear"]').onclick = clearBasket;
}
