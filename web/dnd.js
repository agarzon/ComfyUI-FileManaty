import { STATE, selectedPaths, refresh } from "./filemanaty.js";
import { move as apiMove, copy as apiCopy } from "./api.js";
import { runWithConflicts } from "./clipboard.js";
import { toast } from "./dialogs.js";

const MIME = "application/x-filemanaty";

// Make a grid cell draggable. `name` is the entry name in the current folder.
export function makeDraggable(cell, name) {
    cell.draggable = true;
    cell.addEventListener("dragstart", (e) => {
        if (!STATE.selected.has(name)) { STATE.selected = new Set([name]); STATE.anchorName = name; }
        const payload = { root: STATE.currentRoot, paths: selectedPaths() };
        e.dataTransfer.setData(MIME, JSON.stringify(payload));
        e.dataTransfer.effectAllowed = "copyMove";
    });
}

// Make an element a drop target for in-app move/copy. dstRoot/dstPath = destination dir.
export function makeDropTarget(el, dstRoot, dstPath) {
    el.addEventListener("dragover", (e) => {
        if ([...e.dataTransfer.types].includes(MIME)) {
            e.preventDefault();
            e.dataTransfer.dropEffect = (e.ctrlKey || e.metaKey) ? "copy" : "move";
            el.style.outline = "2px solid #0a84ff";
        }
    });
    el.addEventListener("dragleave", () => { el.style.outline = ""; });
    el.addEventListener("drop", async (e) => {
        el.style.outline = "";
        const raw = e.dataTransfer.getData(MIME);
        if (!raw) return;
        e.preventDefault();
        e.stopPropagation();
        const { root, paths } = JSON.parse(raw);
        const useCopy = e.ctrlKey || e.metaKey;
        const fn = useCopy ? apiCopy : apiMove;
        try {
            const r = await runWithConflicts((onConflict) => fn(root, paths, dstRoot, dstPath, onConflict));
            if (r === null) return;  // cancelled at conflict dialog
            await refresh();
            toast(useCopy ? "Copied" : "Moved", "success");
        } catch (err) {
            toast(err.message || "Drop failed", "error");
        }
    });
}
