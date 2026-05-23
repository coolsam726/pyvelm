/**
 * Unified datetime picker: Flowbite inline calendar + time in one popup.
 * Depends on window.Datepicker from flowbite.min.js.
 */
(function () {
    const PLACEHOLDER_CLASS = "text-body-subtle";

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
            inlineEl.getAttribute("datepicker-format") || "yyyy-mm-dd";
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

        function closePanel() {
            panel.classList.add("hidden");
            trigger.setAttribute("aria-expanded", "false");
            detachOutsideClick();
        }

        function openPanel() {
            panel.classList.remove("hidden");
            trigger.setAttribute("aria-expanded", "true");
            initInlineDatepicker(inlineEl);
            if (draft.date) setInlineDate(inlineEl, draft.date);
            if (timeInput) timeInput.value = draft.time || "00:00";

            outsideListener = (ev) => {
                if (!wrapper.contains(ev.target)) closePanel();
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

    window.pvInitDatetimePickers = function (root) {
        const scope = root || document;
        scope
            .querySelectorAll("[data-pv-datetime-picker]")
            .forEach(wirePicker);
    };
})();
