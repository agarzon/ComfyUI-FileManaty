// Adapter over ComfyUI's settings API. Centralizes the FileManaty settings
// catalog, provides get/subscribe so the rest of the frontend never touches
// app.extensionManager.setting directly. Keeps the blast radius of any
// future ComfyUI Settings API change to this one file.

import { app } from "../../scripts/app.js";

export const KEYS = {
    ALLOW_HIDDEN: "FileManaty.View.AllowHidden",
    SHOW_THUMBNAILS: "FileManaty.View.ShowThumbnails",
    GRID_DENSITY: "FileManaty.View.GridDensity",
    THUMBNAIL_SIZE: "FileManaty.View.ThumbnailSize",
    SORT_FIELD: "FileManaty.Sort.Field",
    SORT_ORDER: "FileManaty.Sort.Order",
    SORT_FOLDERS_FIRST: "FileManaty.Sort.FoldersFirst",
    DEFAULT_ROOT: "FileManaty.Open.DefaultRoot",
    CONFIRM_ON_DELETE: "FileManaty.Confirm.OnDelete",
    CONFIRM_ON_SHIFT_DELETE: "FileManaty.Confirm.OnShiftDelete",
};

const DEFAULTS = {
    [KEYS.ALLOW_HIDDEN]: false,
    [KEYS.SHOW_THUMBNAILS]: true,
    [KEYS.GRID_DENSITY]: "normal",
    [KEYS.THUMBNAIL_SIZE]: "medium",
    [KEYS.SORT_FIELD]: "name",
    [KEYS.SORT_ORDER]: "asc",
    [KEYS.SORT_FOLDERS_FIRST]: true,
    [KEYS.DEFAULT_ROOT]: "Last used",
    [KEYS.CONFIRM_ON_DELETE]: true,
    [KEYS.CONFIRM_ON_SHIFT_DELETE]: true,
};

const subscribers = new Map();  // key -> Set<cb>
const latest = new Map();       // key -> last value seen via onChange (synchronous cache)

function dispatch(key, newValue, oldValue) {
    // ComfyUI's setting store may update asynchronously relative to onChange,
    // so cache newValue here. get() reads this cache first so subscribers
    // (which run synchronously with onChange) see the new value immediately.
    latest.set(key, newValue);
    const subs = subscribers.get(key);
    if (!subs) return;
    for (const cb of subs) {
        try { cb(newValue, oldValue); }
        catch (e) { console.error(`filemanaty settings subscriber for ${key} threw:`, e); }
    }
}

// Build the settings array consumed by app.registerExtension({settings:[...]}).
// rootIds: string[] — the configured root ids fetched from /roots at setup time.
// Used to populate the DefaultRoot combo.
export function buildSettingsDefinitions(rootIds) {
    const rootOptions = ["Last used", ...rootIds];
    return [
        {
            id: KEYS.ALLOW_HIDDEN,
            name: "Show hidden files",
            category: ["FileManaty", "View", "Allow hidden"],
            type: "boolean",
            defaultValue: DEFAULTS[KEYS.ALLOW_HIDDEN],
            tooltip: "Show dotfiles in the file listing. Preview/download of dotfiles is still blocked; toggle is listing-only in v0.3.",
            onChange: (newV, oldV) => dispatch(KEYS.ALLOW_HIDDEN, newV, oldV),
        },
        {
            id: KEYS.SHOW_THUMBNAILS,
            name: "Show thumbnails",
            category: ["FileManaty", "View", "Show thumbnails"],
            type: "boolean",
            defaultValue: DEFAULTS[KEYS.SHOW_THUMBNAILS],
            onChange: (newV, oldV) => dispatch(KEYS.SHOW_THUMBNAILS, newV, oldV),
        },
        {
            id: KEYS.GRID_DENSITY,
            name: "Grid density",
            category: ["FileManaty", "View", "Grid density"],
            type: "combo",
            defaultValue: DEFAULTS[KEYS.GRID_DENSITY],
            options: ["compact", "normal", "comfortable"],
            onChange: (newV, oldV) => dispatch(KEYS.GRID_DENSITY, newV, oldV),
        },
        {
            id: KEYS.THUMBNAIL_SIZE,
            name: "Thumbnail size",
            category: ["FileManaty", "View", "Thumbnail size"],
            type: "combo",
            defaultValue: DEFAULTS[KEYS.THUMBNAIL_SIZE],
            options: ["small", "medium", "large"],
            onChange: (newV, oldV) => dispatch(KEYS.THUMBNAIL_SIZE, newV, oldV),
        },
        {
            id: KEYS.SORT_FIELD,
            name: "Default sort field",
            category: ["FileManaty", "Sort", "Field"],
            type: "combo",
            defaultValue: DEFAULTS[KEYS.SORT_FIELD],
            options: ["name", "size", "mtime", "type"],
            onChange: (newV, oldV) => dispatch(KEYS.SORT_FIELD, newV, oldV),
        },
        {
            id: KEYS.SORT_ORDER,
            name: "Default sort order",
            category: ["FileManaty", "Sort", "Order"],
            type: "combo",
            defaultValue: DEFAULTS[KEYS.SORT_ORDER],
            options: ["asc", "desc"],
            onChange: (newV, oldV) => dispatch(KEYS.SORT_ORDER, newV, oldV),
        },
        {
            id: KEYS.SORT_FOLDERS_FIRST,
            name: "Folders first",
            category: ["FileManaty", "Sort", "Folders first"],
            type: "boolean",
            defaultValue: DEFAULTS[KEYS.SORT_FOLDERS_FIRST],
            onChange: (newV, oldV) => dispatch(KEYS.SORT_FOLDERS_FIRST, newV, oldV),
        },
        {
            id: KEYS.DEFAULT_ROOT,
            name: "Default root on open",
            category: ["FileManaty", "Open", "Default root"],
            type: "combo",
            defaultValue: DEFAULTS[KEYS.DEFAULT_ROOT],
            options: rootOptions,
            onChange: (newV, oldV) => dispatch(KEYS.DEFAULT_ROOT, newV, oldV),
        },
        {
            id: KEYS.CONFIRM_ON_DELETE,
            name: "Confirm before move-to-trash",
            category: ["FileManaty", "Confirm", "On delete"],
            type: "boolean",
            defaultValue: DEFAULTS[KEYS.CONFIRM_ON_DELETE],
            onChange: (newV, oldV) => dispatch(KEYS.CONFIRM_ON_DELETE, newV, oldV),
        },
        {
            id: KEYS.CONFIRM_ON_SHIFT_DELETE,
            name: "Confirm before permanent delete",
            category: ["FileManaty", "Confirm", "On shift-delete"],
            type: "boolean",
            defaultValue: DEFAULTS[KEYS.CONFIRM_ON_SHIFT_DELETE],
            onChange: (newV, oldV) => dispatch(KEYS.CONFIRM_ON_SHIFT_DELETE, newV, oldV),
        },
    ];
}

// Read a setting. Prefers the latest value seen via onChange (synchronous cache),
// then the ComfyUI store, then the catalog default. The cache layer covers the
// case where onChange has fired but the store update hasn't propagated yet.
export function get(key) {
    if (latest.has(key)) return latest.get(key);
    const store = app.extensionManager?.setting;
    if (store && typeof store.get === "function") {
        const v = store.get(key);
        if (v !== undefined && v !== null) return v;
    }
    return DEFAULTS[key];
}

// Programmatic write (e.g., updating LastRoot if we ever move it here).
// In v0.3.0 only consumed for completeness; nothing currently calls this.
export function set(key, value) {
    latest.set(key, value);
    const store = app.extensionManager?.setting;
    if (store && typeof store.set === "function") {
        return store.set(key, value);
    }
    console.warn(`filemanaty.settings.set(${key}): no ComfyUI settings store`);
}

// Subscribe to changes for a given key. Returns an unsubscribe function.
export function subscribe(key, cb) {
    if (!subscribers.has(key)) subscribers.set(key, new Set());
    subscribers.get(key).add(cb);
    return () => subscribers.get(key).delete(cb);
}
