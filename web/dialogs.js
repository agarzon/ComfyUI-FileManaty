import { escapeHtml } from "./filemanaty.js";
import { fetchTrash, restoreTrash, purgeTrash } from "./api.js";

function overlayShell(innerHTML) {
    const back = document.createElement("div");
    back.style.cssText = "position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;";
    const box = document.createElement("div");
    box.style.cssText = "background:#1e1e1e;color:#ddd;border:1px solid #333;border-radius:8px;padding:18px;min-width:320px;max-width:480px;box-shadow:0 10px 40px rgba(0,0,0,.5);";
    box.innerHTML = innerHTML;
    back.appendChild(box);
    document.body.appendChild(back);
    return { back, box, close: () => back.remove() };
}

// Resolve with the typed string, or null if cancelled.
export function promptText(title, initial = "") {
    return new Promise((resolve) => {
        const { box, close } = overlayShell(`
            <div style="font-weight:600;margin-bottom:10px">${escapeHtml(title)}</div>
            <input id="fm-dlg-input" style="width:100%;padding:6px 8px;background:#111;border:1px solid #444;color:#eee;border-radius:4px;box-sizing:border-box">
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
                <button id="fm-dlg-cancel" style="padding:5px 12px;background:#333;border:0;color:#ddd;border-radius:4px;cursor:pointer">Cancel</button>
                <button id="fm-dlg-ok" style="padding:5px 12px;background:#0a84ff;border:0;color:#fff;border-radius:4px;cursor:pointer">OK</button>
            </div>`);
        const input = box.querySelector("#fm-dlg-input");
        input.value = initial;
        input.focus();
        input.select();
        const ok = () => { const v = input.value.trim(); close(); resolve(v || null); };
        box.querySelector("#fm-dlg-ok").onclick = ok;
        box.querySelector("#fm-dlg-cancel").onclick = () => { close(); resolve(null); };
        input.onkeydown = (e) => { e.stopPropagation(); if (e.key === "Enter") ok(); if (e.key === "Escape") { close(); resolve(null); } };
    });
}

// Resolve true (confirmed) / false (cancelled).
export function confirmDialog(title, message, { danger = false } = {}) {
    return new Promise((resolve) => {
        const { box, close } = overlayShell(`
            <div style="font-weight:600;margin-bottom:8px">${escapeHtml(title)}</div>
            <div style="font-size:13px;color:#bbb;margin-bottom:14px">${escapeHtml(message)}</div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button id="fm-dlg-cancel" style="padding:5px 12px;background:#333;border:0;color:#ddd;border-radius:4px;cursor:pointer">Cancel</button>
                <button id="fm-dlg-ok" style="padding:5px 12px;background:${danger ? "#d9433f" : "#0a84ff"};border:0;color:#fff;border-radius:4px;cursor:pointer">Confirm</button>
            </div>`);
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
            <ul style="font-size:12px;color:#bbb;margin:0 0 10px 18px;max-height:120px;overflow:auto">${list}${more}</ul>
            <label style="display:block;font-size:12px;margin-bottom:12px"><input type="checkbox" id="fm-dlg-all"> Do this for all conflicts</label>
            <div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap">
                <button data-p="skip" style="padding:5px 12px;background:#333;border:0;color:#ddd;border-radius:4px;cursor:pointer">Skip</button>
                <button data-p="keep_both" style="padding:5px 12px;background:#2a6;border:0;color:#fff;border-radius:4px;cursor:pointer">Keep both</button>
                <button data-p="replace" style="padding:5px 12px;background:#d9433f;border:0;color:#fff;border-radius:4px;cursor:pointer">Replace</button>
            </div>
            <div style="text-align:right;margin-top:8px"><button id="fm-dlg-cancel" style="padding:3px 10px;background:none;border:0;color:#888;cursor:pointer">Cancel</button></div>`);
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
            <button id="fm-trash-empty" style="padding:4px 10px;background:#d9433f;border:0;color:#fff;border-radius:4px;cursor:pointer">Empty trash</button>
        </div>
        <div id="fm-trash-list" style="max-height:50vh;overflow:auto;font-size:13px"></div>
        <div style="text-align:right;margin-top:12px"><button id="fm-trash-close" style="padding:5px 12px;background:#333;border:0;color:#ddd;border-radius:4px;cursor:pointer">Close</button></div>`);
    box.style.minWidth = "440px";
    const listEl = box.querySelector("#fm-trash-list");

    async function reload() {
        const { items } = await fetchTrash(root);
        if (!items.length) { listEl.innerHTML = "<div style='color:#777;padding:8px'>Trash is empty.</div>"; return; }
        listEl.innerHTML = "";
        for (const it of items) {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:8px;padding:5px 4px;border-bottom:1px solid #2a2a2a";
            row.innerHTML = `<div style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                    <div>${escapeHtml(it.original_name)}</div>
                    <div style="font-size:11px;color:#888">${escapeHtml(it.original_rel_path)} · ${escapeHtml(it.deleted_at || "")}</div>
                </div>
                <button data-restore style="padding:3px 8px;background:#0a84ff;border:0;color:#fff;border-radius:3px;cursor:pointer">Restore</button>
                <button data-purge style="padding:3px 8px;background:#553;border:0;color:#fdd;border-radius:3px;cursor:pointer">Delete</button>`;
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
    const bg = kind === "error" ? "#d9433f" : kind === "success" ? "#2a8" : "#333";
    t.style.cssText = `background:${bg};color:#fff;padding:8px 14px;border-radius:6px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.4);max-width:360px;`;
    t.textContent = message;
    toastHost.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}
