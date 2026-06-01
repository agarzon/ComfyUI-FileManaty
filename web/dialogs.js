import { escapeHtml } from "./filemanaty.js";
import { fetchTrash, restoreTrash, purgeTrash } from "./api.js";

// Number of dialogs currently open, so the overlay's global Esc handler can defer
// to them (a dialog handles its own Esc rather than closing the whole app).
let openDialogs = 0;
export function isDialogOpen() { return openDialogs > 0; }

function overlayShell(innerHTML, onEscape) {
    const back = document.createElement("div");
    back.style.cssText = "position:fixed;inset:0;z-index:9500;background:var(--fm-scrim);display:flex;align-items:center;justify-content:center;";
    const box = document.createElement("div");
    box.style.cssText = "background:var(--fm-bg-elevated);color:var(--fm-text);border:1px solid var(--fm-border);border-radius:8px;padding:18px;min-width:320px;max-width:480px;box-shadow:0 10px 40px rgba(0,0,0,.5);";
    box.innerHTML = innerHTML;
    back.appendChild(box);
    document.body.appendChild(back);
    openDialogs++;
    let closed = false;
    const close = () => {
        if (closed) return;
        closed = true;
        document.removeEventListener("keydown", onKey, true);
        openDialogs = Math.max(0, openDialogs - 1);
        back.remove();
    };
    // Capture phase: Esc cancels THIS dialog and is stopped before it reaches the
    // overlay's bubble-phase Esc handler (which would otherwise close the whole app).
    const onKey = (e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        e.preventDefault();
        close();
        if (onEscape) onEscape();
    };
    document.addEventListener("keydown", onKey, true);
    return { back, box, close };
}

// Resolve with the typed string, or null if cancelled.
export function promptText(title, initial = "") {
    return new Promise((resolve) => {
        const { box, close } = overlayShell(`
            <div style="font-weight:600;margin-bottom:10px">${escapeHtml(title)}</div>
            <input id="fm-dlg-input" style="width:100%;padding:6px 8px;background:var(--fm-bg-input);border:1px solid var(--fm-border);color:var(--fm-text);border-radius:4px;box-sizing:border-box">
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
                <button id="fm-dlg-cancel" style="padding:5px 12px;background:var(--fm-hover);border:0;color:var(--fm-text);border-radius:4px;cursor:pointer">Cancel</button>
                <button id="fm-dlg-ok" style="padding:5px 12px;background:var(--fm-accent);border:0;color:var(--fm-on-accent);border-radius:4px;cursor:pointer">OK</button>
            </div>`, () => resolve(null));
        const input = box.querySelector("#fm-dlg-input");
        input.value = initial;
        input.focus();
        input.select();
        const ok = () => { const v = input.value.trim(); close(); resolve(v || null); };
        box.querySelector("#fm-dlg-ok").onclick = ok;
        box.querySelector("#fm-dlg-cancel").onclick = () => { close(); resolve(null); };
        input.onkeydown = (e) => { e.stopPropagation(); if (e.key === "Enter") ok(); };
    });
}

// Resolve true (confirmed) / false (cancelled).
export function confirmDialog(title, message, { danger = false } = {}) {
    return new Promise((resolve) => {
        const { box, close } = overlayShell(`
            <div style="font-weight:600;margin-bottom:8px">${escapeHtml(title)}</div>
            <div style="font-size:13px;color:var(--fm-text-muted);margin-bottom:14px">${escapeHtml(message)}</div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button id="fm-dlg-cancel" style="padding:5px 12px;background:var(--fm-hover);border:0;color:var(--fm-text);border-radius:4px;cursor:pointer">Cancel</button>
                <button id="fm-dlg-ok" style="padding:5px 12px;background:${danger ? "var(--fm-danger)" : "var(--fm-accent)"};border:0;color:var(--fm-on-accent);border-radius:4px;cursor:pointer">Confirm</button>
            </div>`, () => resolve(false));
        box.querySelector("#fm-dlg-ok").onclick = () => { close(); resolve(true); };
        box.querySelector("#fm-dlg-cancel").onclick = () => { close(); resolve(false); };
    });
}

// Conflict resolution. names = array of conflicting names.
// Resolves { policy: "replace"|"keep_both"|"skip", all: bool } or null if cancelled.
export function conflictDialog(names) {
    return new Promise((resolve) => {
        const list = names.slice(0, 8).map((n) => `<li>${escapeHtml(n)}</li>`).join("");
        const more = names.length > 8 ? `<li>…and ${names.length - 8} more</li>` : "";
        const { box, close } = overlayShell(`
            <div style="font-weight:600;margin-bottom:8px">${names.length} item(s) already exist</div>
            <ul style="font-size:12px;color:var(--fm-text-muted);margin:0 0 10px 18px;max-height:120px;overflow:auto">${list}${more}</ul>
            <label style="display:block;font-size:12px;margin-bottom:12px"><input type="checkbox" id="fm-dlg-all"> Do this for all conflicts</label>
            <div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap">
                <button data-p="skip" style="padding:5px 12px;background:var(--fm-hover);border:0;color:var(--fm-text);border-radius:4px;cursor:pointer">Skip</button>
                <button data-p="keep_both" style="padding:5px 12px;background:#2a6;border:0;color:var(--fm-on-accent);border-radius:4px;cursor:pointer">Keep both</button><!-- status color -->
                <button data-p="replace" style="padding:5px 12px;background:var(--fm-danger);border:0;color:var(--fm-on-accent);border-radius:4px;cursor:pointer">Replace</button>
            </div>
            <div style="text-align:right;margin-top:8px"><button id="fm-dlg-cancel" style="padding:3px 10px;background:none;border:0;color:var(--fm-text-muted);cursor:pointer">Cancel</button></div>`, () => resolve(null));
        box.querySelectorAll("button[data-p]").forEach((b) => {
            b.onclick = () => {
                const all = box.querySelector("#fm-dlg-all").checked;
                close();
                resolve({ policy: b.dataset.p, all });
            };
        });
        box.querySelector("#fm-dlg-cancel").onclick = () => { close(); resolve(null); };
    });
}

// Opens a per-root trash panel. onChange() is called after restore/purge so the
// caller can refresh the main grid.
export async function trashView(root, onChange) {
    const { box, close } = overlayShell(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <div style="font-weight:600">Trash — ${escapeHtml(root)}</div>
            <button id="fm-trash-empty" style="padding:4px 10px;background:var(--fm-danger);border:0;color:var(--fm-on-accent);border-radius:4px;cursor:pointer">Empty trash</button>
        </div>
        <div id="fm-trash-list" style="max-height:50vh;overflow:auto;font-size:13px"></div>
        <div style="text-align:right;margin-top:12px"><button id="fm-trash-close" style="padding:5px 12px;background:var(--fm-hover);border:0;color:var(--fm-text);border-radius:4px;cursor:pointer">Close</button></div>`);
    box.style.minWidth = "440px";
    const listEl = box.querySelector("#fm-trash-list");

    async function reload() {
        const { items } = await fetchTrash(root);
        if (!items.length) { listEl.innerHTML = "<div style='color:var(--fm-text-muted);padding:8px'>Trash is empty.</div>"; return; }
        listEl.innerHTML = "";
        for (const it of items) {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:8px;padding:5px 4px;border-bottom:1px solid var(--fm-border)";
            row.innerHTML = `<div style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                    <div>${escapeHtml(it.original_name)}</div>
                    <div style="font-size:11px;color:var(--fm-text-muted)">${escapeHtml(it.original_rel_path)} · ${escapeHtml(it.deleted_at || "")}</div>
                </div>
                <button data-restore style="padding:3px 8px;background:var(--fm-accent);border:0;color:var(--fm-on-accent);border-radius:3px;cursor:pointer">Restore</button>
                <button data-purge style="padding:3px 8px;background:#553;border:0;color:var(--fm-danger);border-radius:3px;cursor:pointer">Delete</button><!-- status color -->`;
            row.querySelector("[data-restore]").onclick = async () => {
                try {
                    const r = await restoreWithConflict(root, it.id);
                    if (r !== null) { await reload(); onChange && onChange(); toast("Restored", "success"); }
                } catch (e) { toast(e.message, "error"); }
            };
            row.querySelector("[data-purge]").onclick = async () => {
                if (!(await confirmDialog("Permanently delete?", it.original_name, { danger: true }))) return;
                try { await purgeTrash(root, { ids: [it.id] }); await reload(); onChange && onChange(); }
                catch (e) { toast(e.message, "error"); }
            };
            listEl.appendChild(row);
        }
    }

    box.querySelector("#fm-trash-empty").onclick = async () => {
        if (!(await confirmDialog("Empty trash?", "All trashed items will be permanently deleted.", { danger: true }))) return;
        try { await purgeTrash(root, { all: true }); await reload(); onChange && onChange(); }
        catch (e) { toast(e.message, "error"); }
    };
    box.querySelector("#fm-trash-close").onclick = close;
    await reload();
}

// Restore one item, resolving a 409 with the conflict dialog (single id).
async function restoreWithConflict(root, id) {
    try {
        return await restoreTrash(root, [id], null);
    } catch (e) {
        if (e.status !== 409) throw e;
        const choice = await conflictDialog(e.conflicts || []);
        if (!choice) return null;
        return await restoreTrash(root, [id], choice.policy);
    }
}

let toastHost = null;
export function toast(message, kind = "info") {
    if (!toastHost) {
        toastHost = document.createElement("div");
        toastHost.style.cssText = "position:fixed;bottom:18px;right:18px;z-index:9600;display:flex;flex-direction:column;gap:8px;";
        document.body.appendChild(toastHost);
    }
    const t = document.createElement("div");
    // success/error sit on fixed status-color bars (fixed white text); info is a
    // neutral themed bar whose bg+text flip together with the theme.
    const bg = kind === "error" ? "#d9433f" /* status color */ : kind === "success" ? "#2a8" /* status color */ : "var(--fm-bg-elevated)";
    const fg = (kind === "error" || kind === "success") ? "#fff" : "var(--fm-text)";
    t.style.cssText = `background:${bg};color:${fg};padding:8px 14px;border-radius:6px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.4);max-width:360px;`;
    t.textContent = message;
    toastHost.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}
