// Favorite folders: shortcuts pinned above the tree. A favorite is only a root
// id plus a root-relative path — the same pair every endpoint already takes —
// so nothing is stored server-side and no new route is needed.
//
// Storage sits next to filemanaty.lastRoot in localStorage rather than in
// ComfyUI Settings: the settings catalog has no widget for a list, and a raw
// JSON blob in the settings dialog is a corruption surface. Everything below
// the load/save pair is pure, so `node --test tests/test_favorites.mjs` can
// reach it without a DOM.

const STORE_KEY = "filemanaty.favorites";

const same = (f, root, path) => f.root === root && f.path === path;

export function isFavorite(list, root, path) {
    return list.some((f) => same(f, root, path));
}

export function toggleIn(list, root, path) {
    return isFavorite(list, root, path)
        ? list.filter((f) => !same(f, root, path))
        : [...list, { root, path }];
}

// Stored JSON is only as trustworthy as the last thing that wrote it — an older
// format or a hand-edited value must not take the tree down with it.
export function load() {
    try {
        const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
        if (!Array.isArray(raw)) return [];
        return raw.filter((f) => f && typeof f.root === "string" && typeof f.path === "string");
    } catch {
        return [];
    }
}

export function save(list) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(list)); } catch {}
}
