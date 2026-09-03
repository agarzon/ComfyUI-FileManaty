// Pure list logic behind favorite folders — run with:  node --test tests/test_favorites.mjs
// The tree section and the toolbar star need a DOM and are checked in the browser.
import { test } from "node:test";
import assert from "node:assert/strict";

import { isFavorite, toggleIn } from "../web/favorites.js";

test("toggling adds once and removes the same folder", () => {
    const one = toggleIn([], "output", "pics");
    assert.deepEqual(one, [{ root: "output", path: "pics" }]);
    assert.ok(isFavorite(one, "output", "pics"));
    assert.deepEqual(toggleIn(one, "output", "pics"), []);
});

test("the same path in another root is a different favorite", () => {
    const list = toggleIn(toggleIn([], "output", "pics"), "input", "pics");
    assert.equal(list.length, 2);
    assert.ok(isFavorite(list, "input", "pics"));
    assert.deepEqual(toggleIn(list, "input", "pics"), [{ root: "output", path: "pics" }]);
});

test("a root itself is favoritable and distinct from its children", () => {
    const list = toggleIn([], "output", "");
    assert.ok(isFavorite(list, "output", ""));
    assert.ok(!isFavorite(list, "output", "pics"));
});

test("toggleIn does not mutate the list it is given", () => {
    const before = [{ root: "output", path: "pics" }];
    toggleIn(before, "output", "raw");
    toggleIn(before, "output", "pics");
    assert.deepEqual(before, [{ root: "output", path: "pics" }]);
});
