// Drag-to-resize for the FileManaty overlay's tree and preview panes.
// Mirrors ComfyUI/PrimeVue Splitter conventions (localStorage persistence,
// min-size clamps, col-resize gutters) without a Vue dependency. The middle
// grid track stays `1fr` and absorbs the difference, so the thumbnail grid
// keeps auto-reflowing and keyboard nav's computeGridColumns() stays correct.

const LS_TREE = "filemanaty.layout.treeWidth";
const LS_PREVIEW = "filemanaty.layout.previewWidth";

const DEFAULT_TREE = "200px";
const DEFAULT_PREVIEW = "34%";

const MIN_TREE = 120;    // px
const MIN_PREVIEW = 160; // px
const MIN_GRID = 200;    // px — the middle pane is never crushed below this
const GUTTER = 4;        // px — matches ComfyUI/PrimeVue's default gutter

function applyColumns(bodyEl, treeCol, previewCol) {
    bodyEl.style.gridTemplateColumns =
        `${treeCol} ${GUTTER}px 1fr ${GUTTER}px ${previewCol}`;
}

function readStored(key) {
    const v = parseInt(localStorage.getItem(key), 10);
    return Number.isFinite(v) && v > 0 ? v : null;
}

export function initPaneResize(bodyEl) {
    const treeEl = bodyEl.querySelector("#fm-tree");
    const previewEl = bodyEl.querySelector("#fm-preview");

    // Two gutter elements become grid items. DOM order must end up:
    // tree, gutTree, grid, gutPreview, preview.
    const gutTree = document.createElement("div");
    const gutPreview = document.createElement("div");
    gutTree.className = "fm-gutter";
    gutPreview.className = "fm-gutter";
    treeEl.after(gutTree);
    previewEl.before(gutPreview);

    // Current track values, applied to the grid. Only the dragged side is
    // converted to px; the other keeps its default string until touched.
    const tStored = readStored(LS_TREE);
    const pStored = readStored(LS_PREVIEW);
    let treeCol = tStored != null ? `${tStored}px` : DEFAULT_TREE;
    let previewCol = pStored != null ? `${pStored}px` : DEFAULT_PREVIEW;
    applyColumns(bodyEl, treeCol, previewCol);

    function startDrag(which, e) {
        e.preventDefault();
        const rect = bodyEl.getBoundingClientRect();
        const prevUserSelect = document.body.style.userSelect;
        document.body.style.userSelect = "none";
        document.body.style.cursor = "col-resize";
        let moved = false;

        function onMove(ev) {
            moved = true;
            const total = rect.width;
            if (which === "tree") {
                const maxTree =
                    total - GUTTER * 2 - MIN_GRID - previewEl.getBoundingClientRect().width;
                let w = ev.clientX - rect.left;
                w = Math.max(MIN_TREE, Math.min(w, maxTree));
                treeCol = `${Math.round(w)}px`;
            } else {
                const maxPreview =
                    total - GUTTER * 2 - MIN_GRID - treeEl.getBoundingClientRect().width;
                let w = rect.right - ev.clientX;
                w = Math.max(MIN_PREVIEW, Math.min(w, maxPreview));
                previewCol = `${Math.round(w)}px`;
            }
            applyColumns(bodyEl, treeCol, previewCol);
        }

        function onUp() {
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
            document.body.style.userSelect = prevUserSelect;
            document.body.style.cursor = "";
            if (!moved) return; // a plain click should not freeze a % default to px
            if (which === "tree") {
                localStorage.setItem(
                    LS_TREE, String(Math.round(treeEl.getBoundingClientRect().width)));
            } else {
                localStorage.setItem(
                    LS_PREVIEW, String(Math.round(previewEl.getBoundingClientRect().width)));
            }
        }

        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
    }

    // Capture the pointer on the gutter so drags stay tracked on touch/stylus
    // (events still bubble to the document listeners below).
    gutTree.addEventListener("pointerdown", (e) => {
        gutTree.setPointerCapture?.(e.pointerId);
        startDrag("tree", e);
    });
    gutPreview.addEventListener("pointerdown", (e) => {
        gutPreview.setPointerCapture?.(e.pointerId);
        startDrag("preview", e);
    });

    // Double-click a gutter resets that column to its CSS default.
    gutTree.addEventListener("dblclick", () => {
        localStorage.removeItem(LS_TREE);
        treeCol = DEFAULT_TREE;
        applyColumns(bodyEl, treeCol, previewCol);
    });
    gutPreview.addEventListener("dblclick", () => {
        localStorage.removeItem(LS_PREVIEW);
        previewCol = DEFAULT_PREVIEW;
        applyColumns(bodyEl, treeCol, previewCol);
    });
}
