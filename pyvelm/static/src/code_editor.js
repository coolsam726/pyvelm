/**
 * Code editor field — CodeMirror 6 + per-language packs + VSCode theme.
 *
 *   npm run build:code-editor
 *
 * Loaded from `pyvelm/templates/layouts/main.html` BEFORE alpine.js so that
 * `Alpine.data('pvCodeEditor', …)` is registered on the `alpine:init` event.
 *
 * The editor instances live outside Alpine state (see the long comment in
 * `mail_editor.js`): CodeMirror keeps internal identity invariants that
 * Alpine's reactive Proxies would break.
 */
import {
    applyFormatToView,
    buildCodeView,
    canFormatLanguage,
    getDocContent,
    reconfigureTheme,
} from './codemirror_field.js';

const VIEWS = new WeakMap(); // host element → EditorView

function getViews(host) {
    return VIEWS.get(host) || null;
}

function setView(host, view) {
    VIEWS.set(host, view);
}

function parseConfig(el) {
    const b64 = el?.getAttribute('data-pv-config');
    if (!b64) return {};
    try {
        return JSON.parse(atob(b64));
    } catch {
        return {};
    }
}

function registerAlpine() {
    if (!window.Alpine) {
        console.error('[pvCodeEditor] Alpine.js not found');
        return;
    }
    window.Alpine.data('pvCodeEditor', () => ({
        name: 'code',
        language: 'text',
        readonly: false,
        code: '',
        copied: false,
        formatError: '',

        init() {
            const cfg = parseConfig(this.$root);
            this.name = cfg.name || 'code';
            this.language = (cfg.language || 'text').toLowerCase();
            this.readonly = !!cfg.readonly;
            this.code = cfg.initial ?? '';

            this.$root.classList.toggle('pv-code-editor--readonly', this.readonly);

            this.$nextTick(() => this.mountEditor());

            this._themeObserver = new MutationObserver(() => this.applyTheme());
            this._themeObserver.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['class'],
            });
        },

        mountEditor() {
            const mount = this.$refs.mount;
            if (!mount) return;
            const view = buildCodeView(mount, {
                content: this.code,
                language: this.language,
                readonly: this.readonly,
                onUpdate: (value) => {
                    this.code = value;
                },
            });
            setView(this.$root, view);
            this.applyTheme();
        },

        applyTheme() {
            reconfigureTheme(getViews(this.$root));
        },

        canFormat() {
            return canFormatLanguage(this.language) && !this.readonly;
        },

        formatDocument() {
            this.formatError = '';
            const view = getViews(this.$root);
            if (!view) return;
            const after = applyFormatToView(view, this.language, (value) => {
                this.code = value;
            });
            if (after === null) {
                this.formatError = 'Could not format (invalid syntax?)';
                setTimeout(() => {
                    this.formatError = '';
                }, 2500);
            }
        },

        async copyToClipboard() {
            try {
                await navigator.clipboard.writeText(this.code || '');
                this.copied = true;
                setTimeout(() => {
                    this.copied = false;
                }, 1500);
            } catch (err) {
                console.warn('[pvCodeEditor] copy failed', err);
            }
        },

        sync() {
            const view = getViews(this.$root);
            if (!view) return;
            this.code = getDocContent(view);
        },

        destroy() {
            const view = getViews(this.$root);
            if (view) {
                try {
                    view.destroy();
                } catch (err) {
                    console.warn('[pvCodeEditor] destroy failed', err);
                }
                VIEWS.delete(this.$root);
            }
            if (this._themeObserver) {
                this._themeObserver.disconnect();
                this._themeObserver = null;
            }
        },
    }));
}

function syncBeforeSubmit() {
    document.querySelectorAll('.pv-code-editor').forEach((el) => {
        const cmp = window.Alpine?.$data(el);
        if (cmp?.sync) cmp.sync();
    });
}

function wireHtmx() {
    if (!document.body) return;
    document.body.addEventListener('htmx:beforeRequest', syncBeforeSubmit);
}

function boot() {
    const register = () => {
        if (window.__pvCodeEditorRegistered) return;
        registerAlpine();
        window.__pvCodeEditorRegistered = true;
    };
    document.addEventListener('alpine:init', register);
    if (document.body) wireHtmx();
    else document.addEventListener('DOMContentLoaded', wireHtmx);
}

boot();
