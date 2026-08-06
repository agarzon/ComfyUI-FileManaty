// The only JS check in the repo — run it with:  node --test tests/test_upload.mjs
// Covers the two pure bits of web/upload.js; the drop walk itself needs a browser.
import { test } from "node:test";
import assert from "node:assert/strict";

import { dirsToCreate, filesFromPicker } from "../web/upload.js";

test("ancestors are created, parents before their children", () => {
    // Only the leaf holds files, so "pics" appears in no entry — mkdir would
    // still fail on "pics/raw" without it.
    assert.deepEqual(
        dirsToCreate([{ dir: "pics/raw" }, { dir: "pics/raw" }, { dir: "" }]),
        ["pics", "pics/raw"],
    );
});

test("dirsToCreate dedupes and stays ordered across siblings", () => {
    const dirs = dirsToCreate([{ dir: "a/b/c" }, { dir: "a/d" }, { dir: "a/b" }]);
    assert.deepEqual(dirs, ["a", "a/b", "a/b/c", "a/d"]);
    for (const d of dirs) {
        const parent = d.slice(0, d.lastIndexOf("/"));
        if (parent) assert.ok(dirs.indexOf(parent) < dirs.indexOf(d), `${parent} after ${d}`);
    }
});

test("picker keeps folder structure and drops hidden paths", () => {
    const f = (name, webkitRelativePath = "") => ({ name, webkitRelativePath });
    assert.deepEqual(
        filesFromPicker([
            f("a.png", "pics/a.png"),
            f("b.png", "pics/.git/b.png"),   // hidden ancestor
            f(".DS_Store", "pics/.DS_Store"),
            f("loose.png"),                  // plain picker: no relative path
        ]).map((e) => [e.file.name, e.dir]),
        [["a.png", "pics"], ["loose.png", ""]],
    );
});
