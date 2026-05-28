import { STATE, selectedPaths, refresh, rerender } from "./filemanaty.js";
import { copy as apiCopy, move as apiMove } from "./api.js";
import { conflictDialog, toast } from "./dialogs.js";

export function doCopy() {
    if (STATE.selected.size === 0) { toast("Nothing selected"); return; }
    STATE.clipboard = { op: "copy", root: STATE.currentRoot, paths: selectedPaths() };
    toast(`Copied ${STATE.clipboard.paths.length} item(s)`);
    rerender();
}

export function doCut() {
    if (STATE.selected.size === 0) { toast("Nothing selected"); return; }
    STATE.clipboard = { op: "cut", root: STATE.currentRoot, paths: selectedPaths() };
    toast(`Cut ${STATE.clipboard.paths.length} item(s)`);
    rerender();
}

export async function doPaste() {
    const clip = STATE.clipboard;
    if (!clip || clip.paths.length === 0) { toast("Clipboard empty"); return; }
    const fn = clip.op === "cut" ? apiMove : apiCopy;
    const result = await runWithConflicts((onConflict) =>
        fn(clip.root, clip.paths, STATE.currentRoot, STATE.currentPath, onConflict));
    if (result === null) return;  // cancelled at conflict dialog
    if (clip.op === "cut") STATE.clipboard = null;
    await refresh();
    toast(clip.op === "cut" ? "Moved" : "Copied", "success");
}

// Run an API call that may 409. On conflict, ask once and retry with the chosen
// single policy (matches the backend's one-policy-per-request model).
export async function runWithConflicts(call) {
    try {
        return await call(null);
    } catch (e) {
        if (e.status !== 409) throw e;
        const choice = await conflictDialog(e.conflicts || []);
        if (!choice) return null;       // cancelled
        return await call(choice.policy);
    }
}
