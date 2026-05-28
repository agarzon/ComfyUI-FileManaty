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

export async function fetchList(rootId, relPath) {
    const q = new URLSearchParams({ root: rootId, path: relPath });
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
