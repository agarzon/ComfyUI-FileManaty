// Thin wrapper over fetch for /filemanaty/api/v1/*.
// NOTE: We use plain fetch() here instead of app.api.fetchApi() because
// ComfyUI's fetchApi prepends /api to any URL that doesn't already start
// with /api, which would produce /api/filemanaty/api/v1/... (double-prefix).
// Our routes live at /filemanaty/api/v1/* so we bypass fetchApi entirely.
// If ComfyUI ever requires auth headers on custom routes, re-add:
//   import { app } from "../../scripts/app.js";
// and use: app.api.fetchApi("/api" + path) with the /api prefix baked in.

const BASE = "/filemanaty/api/v1";

async function getJSON(url) {
    const resp = await fetch(url, { cache: "no-cache" });
    const body = await resp.json();
    if (!body.ok) {
        const err = new Error(body.error?.message || "unknown error");
        err.code = body.error?.code;
        err.status = resp.status;
        throw err;
    }
    return body.data;
}

export async function fetchRoots() {
    return getJSON(`${BASE}/roots`);
}

export async function fetchList(rootId, relPath, { includeHidden = false } = {}) {
    const q = new URLSearchParams({ root: rootId, path: relPath });
    if (includeHidden) q.set("include_hidden", "true");
    return getJSON(`${BASE}/list?${q.toString()}`);
}

export function thumbnailURL(rootId, relPath) {
    const q = new URLSearchParams({ root: rootId, path: relPath });
    return `${BASE}/thumbnail?${q.toString()}`;
}

export function previewURL(rootId, relPath) {
    const q = new URLSearchParams({ root: rootId, path: relPath });
    return `${BASE}/preview?${q.toString()}`;
}

export function downloadURL(rootId, relPath) {
    const q = new URLSearchParams({ root: rootId, path: relPath });
    return `${BASE}/download?${q.toString()}`;
}

export async function fetchMetadata(rootId, relPath) {
    const q = new URLSearchParams({ root: rootId, path: relPath });
    return getJSON(`${BASE}/metadata?${q.toString()}`);
}

async function postJSON(path, body, { query } = {}) {
    const url = query ? `${BASE}${path}?${new URLSearchParams(query)}` : `${BASE}${path}`;
    const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!data.ok) {
        const err = new Error(data.error?.message || "request failed");
        err.code = data.error?.code;
        err.status = resp.status;
        err.conflicts = data.error?.conflicts || [];
        throw err;
    }
    return data.data;
}

export function mkdir(root, path, name, onConflict) {
    return postJSON("/mkdir", { root, path, name, on_conflict: onConflict ?? null });
}
export function rename(root, path, name, onConflict) {
    return postJSON("/rename", { root, path, name, on_conflict: onConflict ?? null });
}
export function del(root, items, permanent = false) {
    return postJSON("/delete", { root, items, permanent });
}
export function copy(srcRoot, srcItems, dstRoot, dstPath, onConflict) {
    return postJSON("/copy", { src_root: srcRoot, src_items: srcItems, dst_root: dstRoot, dst_path: dstPath, on_conflict: onConflict ?? null });
}
export function move(srcRoot, srcItems, dstRoot, dstPath, onConflict) {
    return postJSON("/move", { src_root: srcRoot, src_items: srcItems, dst_root: dstRoot, dst_path: dstPath, on_conflict: onConflict ?? null });
}
export function fetchTrash(root) {
    return getJSON(`${BASE}/trash/list?${new URLSearchParams({ root })}`);
}
export function restoreTrash(root, ids, onConflict) {
    return postJSON("/trash/restore", { root, ids, on_conflict: onConflict ?? null });
}
export function purgeTrash(root, { ids, all } = {}) {
    return postJSON("/trash/purge", all ? { root, all: true } : { root, ids });
}

// Multipart upload. `files` is a FileList/array of File. Returns the result data.
// onConflict (optional) is sent as a query param so the body stays pure file data.
export async function uploadFiles(root, path, files, onConflict) {
    const form = new FormData();
    form.append("root", root);
    form.append("path", path);
    for (const f of files) form.append("file", f, f.name);
    const q = onConflict ? `?${new URLSearchParams({ on_conflict: onConflict })}` : "";
    const resp = await fetch(`${BASE}/upload${q}`, { method: "POST", body: form });
    const data = await resp.json();
    if (!data.ok) {
        const err = new Error(data.error?.message || "upload failed");
        err.code = data.error?.code;
        err.status = resp.status;
        err.conflicts = data.error?.conflicts || [];
        throw err;
    }
    return data.data;
}
