// The transfer tray: one row per queued file, an aggregate bar over total bytes,
// speed and ETA. Mounted on document.body, not the overlay, so closing the file
// manager leaves the view (and the transfer) alone.
//
// The formatting and rate helpers stay pure so `node --test tests/test_transfers.mjs`
// can reach them; everything below transferTray() needs a DOM.

export function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let v = n / 1024, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "—";
    const s = Math.round(seconds);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

// Bytes/second across the whole sample window, or null while too fresh to tell.
// The delta between two consecutive events swings hard enough to make an ETA
// computed from it unreadable; a window of a few seconds settles it.
export function speedFrom(samples) {
    if (samples.length < 2) return null;
    const first = samples[0], last = samples[samples.length - 1];
    const dt = (last.t - first.t) / 1000;
    if (dt <= 0) return null;
    return (last.sent - first.sent) / dt;
}

const SAMPLE_WINDOW_MS = 3000;
const TICK_MS = 400;
// ponytail: past this many files the tray drops the per-file rows and shows the
// aggregate only — building thousands of rows costs more than it tells anyone.
// Virtualize the list if someone actually wants per-row cancel at that size.
const MAX_ROWS = 200;

const BTN = "background:none;border:0;color:var(--fm-text-muted);cursor:pointer;padding:0 4px;font-size:13px;line-height:1";

// `items` is [{name, size}]. onAbortActive() is called when the row currently in
// flight is cancelled, individually or by cancel-all; the caller aborts its own
// request. Cancellation of a not-yet-started row is recorded here — the caller
// asks cancelled(i) before starting it.
export function transferTray(items, onAbortActive) {
    const rows = items.map((it) => ({ name: it.name, size: it.size, sent: 0, status: "queued" }));
    const total = rows.reduce((a, r) => a + r.size, 0);
    const samples = [];
    let active = -1;
    let finished = false;

    const el = document.createElement("div");
    el.style.cssText = "position:fixed;bottom:18px;left:18px;z-index:9600;width:340px;background:var(--fm-bg-elevated);color:var(--fm-text);border:1px solid var(--fm-border);border-radius:6px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.4);overflow:hidden;";
    el.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;padding:8px 10px 6px">
            <div data-fm-title style="flex:1;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>
            <button data-fm-cancel-all title="Cancel all" aria-label="Cancel all transfers" style="${BTN}">✕</button>
        </div>
        <div style="padding:0 10px"><progress max="${total}" value="0" style="display:block;width:100%;height:6px"></progress></div>
        <div data-fm-stats style="padding:4px 10px 8px;color:var(--fm-text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>
        <div data-fm-rows style="max-height:180px;overflow:auto"></div>`;
    document.body.appendChild(el);

    const titleEl = el.querySelector("[data-fm-title]");
    const statsEl = el.querySelector("[data-fm-stats]");
    const cancelAllEl = el.querySelector("[data-fm-cancel-all]");
    const barEl = el.querySelector("progress");
    const rowsEl = el.querySelector("[data-fm-rows]");

    const rowEls = rows.length <= MAX_ROWS ? rows.map((r, i) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:8px;padding:4px 10px;border-top:1px solid var(--fm-border)";
        row.innerHTML = `<div data-fm-name style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>
            <div data-fm-state style="color:var(--fm-text-muted);white-space:nowrap"></div>
            <button data-fm-x title="Cancel" aria-label="Cancel transfer" style="${BTN}">✕</button>`;
        row.querySelector("[data-fm-name]").textContent = r.name;
        row.querySelector("[data-fm-x]").onclick = () => cancel(i);
        rowsEl.appendChild(row);
        return row;
    }) : [];

    function cancel(i) {
        if (finished || rows[i].status === "done" || rows[i].status === "failed") return;
        if (i === active) { onAbortActive(); return; }   // the caller's catch calls finish()
        rows[i].status = "cancelled";
        render();
    }

    function cancelAll() {
        if (finished) { el.remove(); return; }
        for (let i = 0; i < rows.length; i++) if (rows[i].status === "queued") rows[i].status = "cancelled";
        if (active >= 0) onAbortActive();
        render();
    }
    cancelAllEl.onclick = cancelAll;

    const sentTotal = () => rows.reduce((a, r) => a + r.sent, 0);

    function render() {
        const sent = sentTotal();
        barEl.value = sent;
        // The row in flight names the position; cancelling something further down
        // the queue must not advance the count of the upload still running.
        const settled = rows.filter((r) => r.status !== "queued" && r.status !== "active").length;
        const at = active >= 0 ? active + 1 : Math.min(settled + 1, rows.length);
        titleEl.textContent = `Uploading ${at} of ${rows.length}`;

        // A retry rewinds the total; samples taken before it would read as a
        // negative rate, so they are dropped rather than averaged in.
        const now = Date.now();
        if (samples.length && samples[samples.length - 1].sent > sent) samples.length = 0;
        samples.push({ t: now, sent });
        while (samples.length > 1 && samples[0].t < now - SAMPLE_WINDOW_MS) samples.shift();
        const speed = finished ? null : speedFrom(samples);
        const rate = speed > 0 ? ` · ${formatBytes(Math.round(speed))}/s · ${formatDuration((total - sent) / speed)} left` : "";
        statsEl.textContent = `${formatBytes(sent)} of ${formatBytes(total)}${rate}`;

        rowEls.forEach((row, i) => {
            const r = rows[i];
            row.querySelector("[data-fm-state]").textContent =
                r.status === "active" ? `${Math.floor((r.sent / (r.size || 1)) * 100)}%`
                : r.status === "done" ? "✓"
                : r.status === "failed" ? "Failed"
                : r.status === "cancelled" ? "Cancelled"
                : "Queued";
            row.style.opacity = r.status === "cancelled" || r.status === "failed" ? "0.6" : "";
            row.querySelector("[data-fm-x]").style.visibility =
                r.status === "queued" || r.status === "active" ? "" : "hidden";
        });
    }

    const timer = setInterval(render, TICK_MS);
    render();

    return {
        cancelled: (i) => rows[i].status === "cancelled",
        // Bytes restart from zero: a row is only ever started on a fresh request,
        // and a retry after a conflict has to un-count the attempt that failed.
        start(i) { active = i; rows[i].status = "active"; rows[i].sent = 0; render(); },
        progress(i, loaded) { rows[i].sent = Math.min(loaded, rows[i].size); },
        finish(i, status) {
            active = -1;
            rows[i].status = status;
            if (status === "done") rows[i].sent = rows[i].size;
            render();
        },
        // Rows still queued here were never reached (the batch stopped early).
        finishAll() {
            for (const r of rows) if (r.status === "queued" || r.status === "active") r.status = "cancelled";
            finished = true;
            clearInterval(timer);
            render();
            const ok = rows.filter((r) => r.status === "done").length;
            const failed = rows.filter((r) => r.status === "failed").length;
            titleEl.textContent = `Uploaded ${ok} of ${rows.length}${failed ? ` · ${failed} failed` : ""}`;
            cancelAllEl.title = "Dismiss";
            cancelAllEl.setAttribute("aria-label", "Dismiss");
            // Nothing to read on a clean run — anything else stays until dismissed.
            if (ok === rows.length) setTimeout(() => el.remove(), 1500);
        },
    };
}
