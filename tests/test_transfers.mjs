// Pure helpers behind the transfer tray — run with:  node --test tests/test_transfers.mjs
// The tray itself needs a DOM and is checked in the browser.
import { test } from "node:test";
import assert from "node:assert/strict";

import { formatBytes, formatDuration, speedFrom } from "../web/transfers.js";

test("bytes scale and keep one decimal only while small", () => {
    assert.equal(formatBytes(512), "512 B");
    assert.equal(formatBytes(1536), "1.5 KB");
    assert.equal(formatBytes(20 * 1024 * 1024), "20 MB");
    assert.equal(formatBytes(3 * 1024 ** 4), "3.0 TB");
});

test("durations roll up into minutes and hours", () => {
    assert.equal(formatDuration(9.4), "9s");
    assert.equal(formatDuration(80), "1m 20s");
    assert.equal(formatDuration(3720), "1h 2m");
    assert.equal(formatDuration(Infinity), "—");
});

test("speed spans the whole window, not the last pair", () => {
    // A stalled last second must not read as 0 B/s when the window moved 3 MB.
    const samples = [
        { t: 1000, sent: 0 },
        { t: 2000, sent: 3 * 1024 * 1024 },
        { t: 4000, sent: 3 * 1024 * 1024 },
    ];
    assert.equal(speedFrom(samples), 1024 * 1024);
    assert.equal(speedFrom([{ t: 1000, sent: 0 }]), null);
    assert.equal(speedFrom([{ t: 1000, sent: 0 }, { t: 1000, sent: 99 }]), null);
});
