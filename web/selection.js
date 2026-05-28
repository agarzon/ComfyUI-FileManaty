import { STATE, sortedEntries, rerender } from "./filemanaty.js";

// Handle a click on an entry with modifier keys, Explorer-style.
export function clickSelect(entry, ev) {
    const names = sortedEntries().map((e) => e.name);
    if (ev.shiftKey && STATE.anchorName) {
        const a = names.indexOf(STATE.anchorName);
        const b = names.indexOf(entry.name);
        if (a !== -1 && b !== -1) {
            const [lo, hi] = a < b ? [a, b] : [b, a];
            STATE.selected = new Set(names.slice(lo, hi + 1));
        }
    } else if (ev.ctrlKey || ev.metaKey) {
        if (STATE.selected.has(entry.name)) STATE.selected.delete(entry.name);
        else STATE.selected.add(entry.name);
        STATE.anchorName = entry.name;
    } else {
        STATE.selected = new Set([entry.name]);
        STATE.anchorName = entry.name;
    }
    rerender();
}

export function selectAll() {
    STATE.selected = new Set(sortedEntries().map((e) => e.name));
    rerender();
}
