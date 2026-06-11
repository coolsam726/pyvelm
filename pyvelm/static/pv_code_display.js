/** Prism highlight for read-only code display widgets (velmphp parity). */
(function () {
    function highlight(root) {
        if (typeof window.Prism === 'undefined') return;
        (root || document).querySelectorAll('[data-pv-code-display]').forEach((el) => {
            window.Prism.highlightElement(el.querySelector('code') || el);
        });
    }

    document.addEventListener('DOMContentLoaded', () => highlight());
    document.body.addEventListener('htmx:afterSwap', (ev) => highlight(ev.detail?.target));
    document.body.addEventListener('htmx:afterSettle', (ev) => highlight(ev.detail?.target));
})();
