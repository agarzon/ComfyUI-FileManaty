// Turns a drop or a folder pick into a flat [{file, dir}] list, where `dir` is
// the file's folder path relative to the destination ("" = the destination
// itself). Nothing here touches app state or the DOM tree, so the pure parts
// stay importable by `node --test tests/test_upload.mjs`.

// Dotfiles are dropped: the server rejects hidden names in new paths, so one
// stray .DS_Store would fail the request it rides in.
const isHidden = (name) => name.startsWith(".");

// A <input type="file"> FileList. With `webkitdirectory` each File carries a
// webkitRelativePath ("pics/raw/a.png"); with a plain picker it is "".
export function filesFromPicker(fileList) {
    const out = [];
    for (const file of fileList) {
        const parts = (file.webkitRelativePath || file.name).split("/");
        if (parts.some(isHidden)) continue;
        out.push({ file, dir: parts.slice(0, -1).join("/") });
    }
    return out;
}

// A drop. Folders only exist on the item list (dataTransfer.files is flat), and
// that list is emptied the moment this handler awaits — so every entry is
// claimed synchronously here, before the first await.
export function walkDrop(dataTransfer) {
    const roots = [...dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
    if (!roots.length) return Promise.resolve(filesFromPicker(dataTransfer.files));
    return Promise.all(roots.map((e) => walk(e, ""))).then((r) => r.flat());
}

async function walk(entry, dir) {
    if (isHidden(entry.name)) return [];
    if (entry.isFile) {
        const file = await new Promise((res, rej) => entry.file(res, rej));
        return [{ file, dir }];
    }
    const reader = entry.createReader();
    const kids = [];
    // readEntries yields at most 100 per call and signals the end with an empty
    // batch — a single call would silently truncate a large folder.
    for (;;) {
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        kids.push(...batch);
    }
    const sub = dir ? `${dir}/${entry.name}` : entry.name;
    return (await Promise.all(kids.map((k) => walk(k, sub)))).flat();
}

// Every folder the entries need, ancestors included and parents before their
// children — mkdir refuses to create a folder whose parent does not exist yet,
// and an intermediate folder holding no files of its own appears in no entry.
// Empty folders are not carried over: with no file inside, they are in no entry.
export function dirsToCreate(entries) {
    const dirs = new Set();
    for (const { dir } of entries) {
        if (!dir) continue;
        const parts = dir.split("/");
        for (let i = 1; i <= parts.length; i++) dirs.add(parts.slice(0, i).join("/"));
    }
    return [...dirs].sort();
}
