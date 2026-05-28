/**
 * Excel-style keyboard navigation for inline One2many edit tables.
 *
 * Shortcuts (when focus is inside a [data-pv-o2m-root] grid):
 *   Tab / Shift+Tab  — next / previous editable cell (row-major)
 *   Enter            — cell below (Shift+Enter keeps newline in textarea)
 *   Arrow keys       — move between cells (text fields: only at line edges,
 *                      or always with Ctrl/Cmd held)
 *   Escape           — clear cell highlight
 *
 * Click a cell to focus its editor. Active cell gets .pv-o2m-cell--active.
 */
(function () {
    "use strict";

    const SEL_ROOT = "[data-pv-o2m-root]";
    const SEL_ROW = 'tr[data-pv-o2m-row]:not(.line-through):not([data-pv-o2m-empty])';
    const SEL_CELL = "td[data-pv-o2m-cell]";
    const SEL_FOCUSABLE =
        'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])';

    function m2oDropdownOpen(el) {
        const root = el && el.closest && el.closest(".pv-m2o");
        if (!root || !window.Alpine) return false;
        try {
            const data = window.Alpine.$data(root);
            return !!(data && data.open);
        } catch (_) {
            return false;
        }
    }

    function getFocusable(cell) {
        if (!cell) return null;
        return cell.querySelector(SEL_FOCUSABLE);
    }

    function clearActive(root) {
        root.querySelectorAll(".pv-o2m-cell--active").forEach((td) => {
            td.classList.remove("pv-o2m-cell--active");
        });
    }

    function focusCell(td) {
        if (!td) return;
        const root = td.closest(SEL_ROOT);
        if (!root) return;
        clearActive(root);
        td.classList.add("pv-o2m-cell--active");
        const el = getFocusable(td);
        if (el) {
            el.focus({ preventScroll: false });
            if (typeof el.select === "function" && el.type !== "checkbox") {
                try {
                    el.select();
                } catch (_) {
                    /* date inputs, etc. */
                }
            }
        } else {
            td.focus();
        }
    }

    function rowsIn(root) {
        return Array.from(root.querySelectorAll(SEL_ROW));
    }

    function cellsInRow(tr) {
        return Array.from(tr.querySelectorAll(SEL_CELL));
    }

    function coords(td) {
        const tr = td.closest("tr");
        const root = td.closest(SEL_ROOT);
        const rows = rowsIn(root);
        const rowIdx = rows.indexOf(tr);
        const cells = cellsInRow(tr);
        const colIdx = cells.indexOf(td);
        return { root, rows, rowIdx, colIdx, colCount: cells.length };
    }

    function cellAt(root, rowIdx, colIdx) {
        const rows = rowsIn(root);
        const tr = rows[rowIdx];
        if (!tr) return null;
        const cells = cellsInRow(tr);
        return cells[colIdx] || null;
    }

    function addLine(root) {
        const add =
            root.querySelector("[data-pv-o2m-add-row]") ||
            root.querySelector("[data-pv-o2m-add]");
        if (add) add.click();
    }

    function navigate(root, rowIdx, colIdx, dRow, dCol) {
        const rows = rowsIn(root);
        if (!rows.length) {
            if (dRow > 0 || dCol !== 0) addLine(root);
            return;
        }
        const colCount = cellsInRow(rows[0]).length || 1;
        let r = rowIdx;
        let c = colIdx + dCol;

        if (dRow !== 0) {
            r += dRow;
            /* keep column when moving vertically */
        } else if (dCol !== 0) {
            while (c >= colCount) {
                c -= colCount;
                r += 1;
            }
            while (c < 0) {
                c += colCount;
                r -= 1;
            }
        }

        if (r >= rows.length) {
            if (dRow > 0 || dCol > 0) {
                addLine(root);
                const rows2 = rowsIn(root);
                r = rows2.length - 1;
                if (r < 0) return;
            } else {
                r = rows.length - 1;
            }
        }
        if (r < 0) r = 0;
        if (c < 0) c = 0;
        if (c >= colCount) c = colCount - 1;

        const td = cellAt(root, r, c);
        if (td) focusCell(td);
    }

    function textInputAllowsArrow(el, key) {
        if (!el || el.tagName !== "INPUT") return false;
        const t = (el.type || "text").toLowerCase();
        if (t === "text" || t === "search" || t === "email" || t === "url" || t === "") {
            return true;
        }
        return false;
    }

    function shouldNavigateFromText(el, key, ev) {
        if (ev.ctrlKey || ev.metaKey) return true;
        if (!textInputAllowsArrow(el, key)) return true;
        const start = el.selectionStart;
        const end = el.selectionEnd;
        const len = (el.value || "").length;
        if (key === "ArrowLeft") return start === 0 && end === 0;
        if (key === "ArrowRight") return start === len && end === len;
        if (key === "ArrowUp" || key === "ArrowDown") return true;
        return true;
    }

    function onFocusIn(ev) {
        const td = ev.target.closest(SEL_CELL);
        if (!td) return;
        const root = td.closest(SEL_ROOT);
        if (!root) return;
        clearActive(root);
        td.classList.add("pv-o2m-cell--active");
    }

    function onClick(ev) {
        const td = ev.target.closest(SEL_CELL);
        if (!td) return;
        const root = td.closest(SEL_ROOT);
        if (!root || !root.contains(ev.target)) return;
        if (ev.target.closest("[data-pv-o2m-delete]")) return;
        focusCell(td);
    }

    function onKeyDown(ev) {
        const root = ev.target.closest(SEL_ROOT);
        if (!root) return;

        if (m2oDropdownOpen(ev.target)) {
            if (
                ev.key === "ArrowDown" ||
                ev.key === "ArrowUp" ||
                ev.key === "Enter"
            ) {
                return;
            }
        }

        let td = ev.target.closest(SEL_CELL);
        if (!td) {
            const row = ev.target.closest("tr[data-pv-o2m-row]");
            if (row) td = row.querySelector(SEL_CELL);
        }
        if (!td) return;

        const { rowIdx, colIdx } = coords(td);

        if (ev.key === "Escape") {
            clearActive(root);
            return;
        }

        if (ev.key === "Tab") {
            ev.preventDefault();
            navigate(root, rowIdx, colIdx, 0, ev.shiftKey ? -1 : 1);
            return;
        }

        if (ev.key === "Enter") {
            if (ev.target.tagName === "TEXTAREA" && ev.shiftKey) return;
            if (m2oDropdownOpen(ev.target)) return;
            ev.preventDefault();
            navigate(root, rowIdx, colIdx, 1, 0);
            return;
        }

        let dRow = 0;
        let dCol = 0;
        if (ev.key === "ArrowDown") dRow = 1;
        else if (ev.key === "ArrowUp") dRow = -1;
        else if (ev.key === "ArrowRight") dCol = 1;
        else if (ev.key === "ArrowLeft") dCol = -1;
        else return;

        if (!shouldNavigateFromText(ev.target, ev.key, ev)) return;

        ev.preventDefault();
        navigate(root, rowIdx, colIdx, dRow, dCol);
    }

    function bindRoot(root) {
        if (!root || root.dataset.pvO2mGridBound === "1") return;
        root.dataset.pvO2mGridBound = "1";
        root.addEventListener("click", onClick);
    }

    function initRoot(root) {
        if (!root) return;
        bindRoot(root);
    }

    function initAll(scope) {
        const base = scope && scope.querySelectorAll ? scope : document;
        base.querySelectorAll(SEL_ROOT).forEach(initRoot);
    }

    window.pvO2mGridInit = initRoot;
    window.pvO2mGridInitAll = initAll;

    /** Add/delete/reorder rows for inline edit tables (also when revealed via edit_toggle). */
    window.pvO2mBindRoot = function (root) {
        if (!root || root.dataset.pvO2mTableBound === "1") return;
        root.dataset.pvO2mTableBound = "1";

        const tbody = root.querySelector("tbody");
        const tmpl = root.querySelector("template[data-pv-o2m-template]");
        const addLineRow = root.querySelector("[data-pv-o2m-add-row]");
        let nextIdx = parseInt(root.dataset.pvO2mNext, 10) || 0;
        const dragOn = root.dataset.pvO2mDrag === "true";

        function renumber() {
            if (!dragOn || !tbody) return;
            tbody.querySelectorAll("tr[data-pv-o2m-row]").forEach((tr, i) => {
                if (tr.classList.contains("line-through")) return;
                const seq = tr.querySelector("input[data-pv-o2m-seq]");
                if (seq) seq.value = String((i + 1) * 10);
            });
        }

        function rewriteIdx(node, idx) {
            if (!node || node.nodeType !== 1) return;
            ["name", "id", "for"].forEach((a) => {
                if (!node.hasAttribute(a)) return;
                const v = node.getAttribute(a);
                if (v.indexOf("__IDX__") >= 0) {
                    node.setAttribute(a, v.split("__IDX__").join(idx));
                }
            });
            if (node.hasAttribute("x-data")) {
                const xd = node.getAttribute("x-data");
                if (xd.indexOf("__IDX__") >= 0) {
                    node.setAttribute("x-data", xd.split("__IDX__").join(idx));
                }
            }
            for (let i = 0; i < node.children.length; i++) {
                rewriteIdx(node.children[i], idx);
            }
        }

        function addRow() {
            if (!tmpl || !tmpl.content || !tmpl.content.firstElementChild || !tbody) {
                return;
            }
            const idx = String(nextIdx++);
            root.dataset.pvO2mNext = String(nextIdx);
            const row = tmpl.content.firstElementChild.cloneNode(true);
            rewriteIdx(row, idx);
            const emptyRow = tbody.querySelector("[data-pv-o2m-empty]");
            if (emptyRow) emptyRow.remove();
            if (addLineRow) tbody.insertBefore(row, addLineRow);
            else tbody.appendChild(row);
            if (window.Alpine && typeof window.Alpine.initTree === "function") {
                window.Alpine.initTree(row);
            }
            renumber();
            const first = row.querySelector(
                'input:not([type=hidden]),select,textarea',
            );
            if (first) first.focus();
            initRoot(root);
        }

        root.addEventListener("click", (e) => {
            if (
                e.target.closest("[data-pv-o2m-add]") ||
                e.target.closest("[data-pv-o2m-add-row]")
            ) {
                e.preventDefault();
                addRow();
                return;
            }
            const btn = e.target.closest("[data-pv-o2m-delete]");
            if (!btn || !root.contains(btn)) return;
            const tr = btn.closest("tr");
            if (!tr) return;
            const op = tr.querySelector('input[name$="[_op]"]');
            if (op && op.value === "create") {
                tr.remove();
                renumber();
                return;
            }
            if (op) op.value = "delete";
            tr.classList.add("opacity-40", "line-through", "pointer-events-none");
            renumber();
        });

        if (dragOn && tbody) {
            let dragged = null;
            tbody.addEventListener("dragstart", (e) => {
                const tr = e.target.closest("tr[data-pv-o2m-row]");
                if (!tr) return;
                dragged = tr;
                e.dataTransfer.effectAllowed = "move";
                tr.classList.add("opacity-50");
            });
            tbody.addEventListener("dragend", () => {
                if (dragged) dragged.classList.remove("opacity-50");
                dragged = null;
            });
            tbody.addEventListener("dragover", (e) => {
                if (!dragged) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                const tr = e.target.closest("tr[data-pv-o2m-row]");
                if (!tr || tr === dragged) return;
                const rect = tr.getBoundingClientRect();
                const before = e.clientY - rect.top < rect.height / 2;
                tbody.insertBefore(dragged, before ? tr : tr.nextSibling);
            });
            tbody.addEventListener("drop", (e) => {
                if (!dragged) return;
                e.preventDefault();
                renumber();
            });
        }

        initRoot(root);
    };

    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("DOMContentLoaded", () => {
        initAll(document);
        document.querySelectorAll(SEL_ROOT).forEach((root) => {
            if (window.pvO2mBindRoot) window.pvO2mBindRoot(root);
        });
    });
})();
