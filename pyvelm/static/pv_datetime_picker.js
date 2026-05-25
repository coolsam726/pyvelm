/**
 * Unified datetime picker: Flowbite inline calendar + time in one popup.
 * Depends on window.Datepicker from flowbite.min.js.
 */
(function () {
    const PLACEHOLDER_CLASS = "text-body-subtle";
    const FLOAT_MIN_WIDTH = 272;
    const FLOAT_Z = 120;

    function pad(n) {
        return String(n).padStart(2, "0");
    }

    function formatIso(dateStr, timeStr) {
        if (!dateStr) return "";
        return `${dateStr}T${timeStr || "00:00"}`;
    }

    function formatDisplay(iso) {
        if (!iso) return "";
        const norm = iso.replace(" ", "T");
        const [d, t] = norm.split("T");
        return t ? `${d} ${t.slice(0, 5)}` : d;
    }

    function parseHidden(val) {
        if (!val) return { date: "", time: "00:00" };
        const norm = String(val).trim().replace(" ", "T");
        const [date, time = "00:00"] = norm.split("T");
        return { date, time: time.slice(0, 5) };
    }

    function dateFromPicker(inlineEl) {
        const dp = inlineEl && inlineEl.datepicker;
        if (!dp || typeof dp.getDate !== "function") return "";
        const picked = dp.getDate();
        if (!picked) return "";
        const d = Array.isArray(picked) ? picked[0] : picked;
        if (!(d instanceof Date) || Number.isNaN(d.getTime())) return "";
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    function initInlineDatepicker(inlineEl) {
        if (!inlineEl || inlineEl.datepicker || !window.Datepicker) return null;
        const format =
            inlineEl.getAttribute("data-datepicker-format") ||
            inlineEl.getAttribute("datepicker-format") ||
            "yyyy-mm-dd";
        return new window.Datepicker(inlineEl, { format, inline: true });
    }

    function setInlineDate(inlineEl, isoDate) {
        if (!inlineEl || !isoDate) return;
        inlineEl.setAttribute("data-date", isoDate);
        const dp = inlineEl.datepicker;
        if (dp && typeof dp.setDate === "function") {
            dp.setDate(isoDate, { render: true });
        }
    }

    function clearInlineDate(inlineEl) {
        if (!inlineEl) return;
        inlineEl.removeAttribute("data-date");
        const dp = inlineEl.datepicker;
        if (dp && typeof dp.setDate === "function") {
            dp.setDate({ clear: true });
        }
    }

    function wirePicker(wrapper) {
        if (wrapper.dataset.pvDatetimeReady === "1") return;
        wrapper.dataset.pvDatetimeReady = "1";

        const hidden = wrapper.querySelector("[data-pv-datetime-value]");
        const trigger = wrapper.querySelector("[data-pv-datetime-trigger]");
        const display = wrapper.querySelector("[data-pv-datetime-display]");
        const panel = wrapper.querySelector("[data-pv-datetime-panel]");
        const inlineEl = wrapper.querySelector("[data-pv-datetime-inline]");
        const timeInput = wrapper.querySelector("[data-pv-datetime-time]");
        const btnApply = wrapper.querySelector("[data-pv-datetime-apply]");
        const btnClear = wrapper.querySelector("[data-pv-datetime-clear]");
        const placeholder =
            wrapper.dataset.pvDatetimePlaceholder || "Select date and time";

        if (!hidden || !trigger || !display || !panel) return;

        let draft = parseHidden(hidden.value);
        let outsideListener = null;
        let floatReposition = null;

        function refreshDisplay() {
            const iso = hidden.value;
            if (!iso) {
                display.textContent = placeholder;
                display.classList.add(PLACEHOLDER_CLASS);
            } else {
                display.textContent = formatDisplay(iso);
                display.classList.remove(PLACEHOLDER_CLASS);
            }
        }

        function syncDraftFromControls() {
            if (inlineEl) {
                const fromPicker = dateFromPicker(inlineEl);
                if (fromPicker) draft.date = fromPicker;
            }
            if (timeInput) {
                draft.time = timeInput.value || draft.time || "00:00";
            }
        }

        function detachOutsideClick() {
            if (outsideListener) {
                document.removeEventListener("click", outsideListener, true);
                outsideListener = null;
            }
        }

        function detachFloatListeners() {
            if (!floatReposition) return;
            window.removeEventListener("resize", floatReposition);
            window.removeEventListener("scroll", floatReposition, true);
            floatReposition = null;
        }

        function positionFloatingPanel() {
            const rect = trigger.getBoundingClientRect();
            const gap = 4;
            let top = rect.bottom + gap;
            let left = rect.left;
            panel.style.zIndex = String(FLOAT_Z);
            const pw = panel.offsetWidth || FLOAT_MIN_WIDTH;
            const ph = panel.offsetHeight || 320;
            if (left + pw > window.innerWidth - 8) {
                left = Math.max(8, window.innerWidth - pw - 8);
            }
            if (top + ph > window.innerHeight - 8) {
                const above = rect.top - gap - ph;
                if (above >= 8) top = above;
            }
            panel.style.top = `${top}px`;
            panel.style.left = `${left}px`;
            panel.style.minWidth = `${Math.max(rect.width, FLOAT_MIN_WIDTH)}px`;
        }

        function floatPanel() {
            if (panel.parentNode !== document.body) {
                document.body.appendChild(panel);
            }
            panel.classList.add("pv-datetime-panel--floating");
            positionFloatingPanel();
        }

        function dockPanel() {
            detachFloatListeners();
            panel.classList.add("hidden");
            panel.classList.remove("pv-datetime-panel--floating");
            panel.style.top = "";
            panel.style.left = "";
            panel.style.minWidth = "";
            panel.style.zIndex = "";
            if (panel.parentNode !== wrapper) {
                wrapper.appendChild(panel);
            }
        }

        function isPickerClick(target) {
            return (
                target &&
                typeof target.closest === "function" &&
                (target.closest(".datepicker-picker") ||
                    target.closest(".datepicker-dropdown"))
            );
        }

        function closePanel() {
            dockPanel();
            trigger.setAttribute("aria-expanded", "false");
            detachOutsideClick();
        }

        function openPanel() {
            floatPanel();
            panel.classList.remove("hidden");
            trigger.setAttribute("aria-expanded", "true");
            initInlineDatepicker(inlineEl);
            if (draft.date) setInlineDate(inlineEl, draft.date);
            if (timeInput) timeInput.value = draft.time || "00:00";
            positionFloatingPanel();

            floatReposition = () => positionFloatingPanel();
            window.addEventListener("resize", floatReposition);
            window.addEventListener("scroll", floatReposition, true);

            outsideListener = (ev) => {
                const t = ev.target;
                if (wrapper.contains(t) || panel.contains(t)) return;
                if (isPickerClick(t)) return;
                closePanel();
            };
            document.addEventListener("click", outsideListener, true);
        }

        function apply() {
            syncDraftFromControls();
            if (!draft.date) {
                hidden.value = "";
                closePanel();
                refreshDisplay();
                hidden.dispatchEvent(new Event("change", { bubbles: true }));
                return;
            }
            hidden.value = formatIso(draft.date, draft.time);
            closePanel();
            refreshDisplay();
            hidden.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function clearAll() {
            draft = { date: "", time: "00:00" };
            hidden.value = "";
            clearInlineDate(inlineEl);
            if (timeInput) timeInput.value = "";
            closePanel();
            refreshDisplay();
            hidden.dispatchEvent(new Event("change", { bubbles: true }));
        }

        refreshDisplay();

        trigger.addEventListener("click", (ev) => {
            ev.preventDefault();
            if (panel.classList.contains("hidden")) openPanel();
            else closePanel();
        });

        inlineEl?.addEventListener("changeDate", (ev) => {
            const d = ev.detail?.date;
            if (d instanceof Date && !Number.isNaN(d.getTime())) {
                draft.date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                inlineEl.setAttribute("data-date", draft.date);
            }
        });

        timeInput?.addEventListener("change", () => {
            draft.time = timeInput.value || "00:00";
        });

        btnApply?.addEventListener("click", (ev) => {
            ev.preventDefault();
            apply();
        });
        btnClear?.addEventListener("click", (ev) => {
            ev.preventDefault();
            clearAll();
        });

        trigger.addEventListener("keydown", (ev) => {
            if (ev.key === "Escape") closePanel();
        });
    }

    /** Date-only fields: init Flowbite once per input; skip datetime popups. */
    window.pvInitDatepickers = function (root) {
        const scope = root || document;
        if (!window.Datepicker) return;
        scope
            .querySelectorAll("[data-pv-datepicker] [datepicker]")
            .forEach((el) => {
                if (!el || el.datepicker) return;
                const buttons = el.hasAttribute("datepicker-buttons");
                const autohide = el.hasAttribute("datepicker-autohide");
                const format =
                    el.getAttribute("datepicker-format") || "yyyy-mm-dd";
                new window.Datepicker(el, {
                    buttons,
                    autohide,
                    format,
                    container: document.body,
                });
            });
    };

    window.pvInitDatetimePickers = function (root) {
        const scope = root || document;
        scope
            .querySelectorAll("[data-pv-datetime-picker]")
            .forEach(wirePicker);
    };
})();
