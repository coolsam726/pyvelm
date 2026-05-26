/**
 * Email template field: TipTap (Write) + CodeMirror 6 (HTML source).
 *
 *   npm run build:editor
 *
 * Loaded from `pyvelm/templates/layouts/main.html` BEFORE alpine.js so that
 * `Alpine.data('pvHtmlEditor', …)` is registered on the `alpine:init` event.
 *
 * Why the editor refs live outside Alpine state
 * ---------------------------------------------
 * TipTap stores its EditorState (and ProseMirror doc) on the Editor instance.
 * If we assign the instance to a property on the Alpine component (e.g.
 * `this.tipTap = new Editor(…)`), Alpine wraps the entire object — and its
 * internal `view.state`, `state.doc`, etc. — in reactive Proxies. Each access
 * returns a new Proxy view of the underlying object, so two reads of
 * `editor.state.doc` are not `===`. ProseMirror's `applyInner` checks
 * `tr.before === this.doc` to decide whether a transaction is still valid,
 * and the identity check fails — it aborts with "Applying a mismatched
 * transaction".
 *
 * Vue users solve this with `markRaw()`. Alpine has no equivalent, so we keep
 * the editor instances in a module-level WeakMap keyed by the component's
 * root element. Alpine never sees them, never proxies them, and ProseMirror
 * gets the same object identity on every access.
 *
 * The WeakMap is keyed by `this.$root`, not `this.$el`: inside a method that
 * was invoked from a child directive (e.g. `@click="run('bold')"` on a
 * toolbar button), Alpine's `$el` resolves to the directive's element (the
 * button), not the component root. `$root` is documented to always point at
 * the component's x-data host.
 */
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import { EditorState } from '@codemirror/state';
import {
    EditorView,
    keymap,
    lineNumbers,
    highlightActiveLine,
    drawSelection,
} from '@codemirror/view';
import { html } from '@codemirror/lang-html';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { syntaxHighlighting, defaultHighlightStyle } from '@codemirror/language';
import {
    autocompletion,
    completionKeymap,
    completeFromList,
} from '@codemirror/autocomplete';

// host element → { tipTap, codeView }. Lives outside Alpine reactivity.
const EDITORS = new WeakMap();

function getEds(host) {
    let entry = EDITORS.get(host);
    if (!entry) {
        entry = { tipTap: null, codeView: null };
        EDITORS.set(host, entry);
    }
    return entry;
}

function destroyEditor(ed) {
    if (!ed) return;
    try {
        ed.destroy();
    } catch (err) {
        console.warn('[pvHtmlEditor] destroy failed', err);
    }
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

function stripScripts(text) {
    if (!text) return '';
    return text.replace(
        /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
        ''
    );
}

function whenVisible(cb) {
    requestAnimationFrame(() => requestAnimationFrame(cb));
}

function buildTemplateCompletions(variables) {
    const entries = (variables || []).map((v) => ({
        label: v.expr,
        detail: v.label,
        type: 'variable',
        apply: v.snippet || `{{ ${v.expr} }}`,
    }));
    return completeFromList(entries);
}

function createTipTap(mountEl, { content, onUpdate }) {
    mountEl.innerHTML = '';
    const initial = content?.trim() ? content : '<p></p>';
    const editor = new Editor({
        element: mountEl,
        extensions: [
            StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
            Link.configure({
                openOnClick: false,
                HTMLAttributes: { rel: 'noopener noreferrer' },
            }),
        ],
        content: initial,
        editable: true,
        editorProps: {
            attributes: {
                class: 'tiptap pv-tiptap-doc',
                spellcheck: 'true',
                tabindex: '0',
            },
        },
        onUpdate: ({ editor: ed }) => onUpdate(ed.getHTML()),
    });
    whenVisible(() => {
        if (!editor.isDestroyed) editor.commands.focus('end');
    });
    return editor;
}

function createCodeMirror(mountEl, { content, onUpdate, getCompletions }) {
    mountEl.innerHTML = '';
    const completionExt = autocompletion({
        override: [
            (context) => {
                const list = getCompletions?.() || [];
                if (!list.length) return null;
                const word = context.matchBefore(
                    /(?:\{\{\s*)?((?:object|user|company|ctx)(?:\.\w+)*)/
                );
                if (!word && !context.explicit) return null;
                const from = word ? word.from : context.pos;
                const typed = word ? word.text : '';
                const options = list
                    .filter((v) => {
                        const expr = v.expr || '';
                        if (!typed) return true;
                        return expr.startsWith(typed) || expr.includes(typed);
                    })
                    .slice(0, 80)
                    .map((v) => ({
                        label: v.expr,
                        detail: v.label,
                        type: 'variable',
                        apply: v.snippet || `{{ ${v.expr} }}`,
                    }));
                if (!options.length) return null;
                return { from, options, validFor: /^[\w.]*$/ };
            },
            buildTemplateCompletions(getCompletions?.() || []),
        ],
    });

    const state = EditorState.create({
        doc: content ?? '',
        extensions: [
            lineNumbers(),
            highlightActiveLine(),
            drawSelection(),
            history(),
            html(),
            syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
            keymap.of([
                ...defaultKeymap,
                ...historyKeymap,
                ...completionKeymap,
            ]),
            completionExt,
            EditorView.updateListener.of((update) => {
                if (update.docChanged) {
                    onUpdate(update.state.doc.toString());
                }
            }),
        ],
    });
    const view = new EditorView({ state, parent: mountEl });
    whenVisible(() => {
        view.requestMeasure();
        view.focus();
    });
    return view;
}

function registerAlpine() {
    if (!window.Alpine) {
        console.error('[pvHtmlEditor] Alpine.js not found');
        return;
    }

    window.Alpine.data('pvHtmlEditor', () => ({
        // --- config (filled in by init() from data-pv-config) ---
        name: 'body_html',
        readonly: false,
        mailModel: '',

        // --- reactive model state ---
        html: '',
        tab: 'write',
        variables: [],
        variablesLoading: false,
        varQuery: '',
        varPickerOpen: false,
        varCursor: 0,

        // NOTE: there is no `tipTap` / `codeView` property here on purpose.
        // The instances live in the module-level EDITORS WeakMap so Alpine
        // doesn't proxy them. See the module-level comment above.

        init() {
            const cfg = parseConfig(this.$root);
            this.name = cfg.name || 'body_html';
            this.html = cfg.initial ?? '';
            this.readonly = !!cfg.readonly;
            this.tab = this.readonly ? 'preview' : 'write';
            this.mailModel = cfg.mailModel || '';

            getEds(this.$root); // ensure WeakMap entry exists

            // Pick up the current model from the surrounding form's hidden
            // `model` input (the model combobox keeps it in sync).
            const form = this.$root.closest('form');
            if (form && !this.mailModel) {
                const hidden = form.querySelector(
                    'input[type="hidden"][name="model"]'
                );
                if (hidden?.value) this.mailModel = hidden.value;
            }

            // React to model changes (combo-change dispatched by pvCombo).
            if (form) {
                form.addEventListener('combo-change', (e) => {
                    const combo = e.target?.closest?.('.pv-combo');
                    if (!combo || !form.contains(combo)) return;
                    const modelInput = combo.querySelector(
                        'input[type="hidden"][name="model"]'
                    );
                    if (!modelInput) return;
                    const next = e.detail?.value ?? modelInput.value ?? '';
                    if (String(next) !== String(this.mailModel)) {
                        this.mailModel = String(next);
                        this.loadVariables();
                    }
                });
            }

            if (!this.readonly) {
                this.loadVariables();
                this.$nextTick(() => {
                    whenVisible(() => {
                        if (this.tab === 'write') this.ensureWrite();
                    });
                });
            }
        },

        // ----- editor accessors (raw, NOT through Alpine) -----

        _tipTap() {
            return EDITORS.get(this.$root)?.tipTap || null;
        },

        _codeView() {
            return EDITORS.get(this.$root)?.codeView || null;
        },

        _setTipTap(ed) {
            const eds = getEds(this.$root);
            eds.tipTap = ed;
        },

        _setCodeView(view) {
            const eds = getEds(this.$root);
            eds.codeView = view;
        },

        // --- variable picker ---

        showVarPicker() {
            // Variable autocompletion / picker is only meaningful while
            // editing the HTML source. The Write (TipTap) tab inserts
            // {{ … }} as visible text, which is rarely what you want, and
            // the Preview tab is read-only.
            return !this.readonly && this.tab === 'source';
        },

        varPickerNeedQuery() {
            return (
                (this.variables || []).length > 25 &&
                !(this.varQuery || '').trim()
            );
        },

        filteredVarOptions() {
            const rows = this.variables || [];
            const q = (this.varQuery || '').trim().toLowerCase();
            if (rows.length > 25 && !q) return [];
            const filtered = q
                ? rows.filter((v) =>
                      `${v.expr} ${v.label}`.toLowerCase().includes(q)
                  )
                : rows;
            return filtered.slice(0, 50).map((v) => ({
                value: v.expr,
                label: v.expr,
                detail: v.label,
                item: v,
            }));
        },

        varPickerPlaceholder() {
            if (!this.mailModel) return 'Select a model above…';
            if (this.variablesLoading) return 'Loading fields…';
            const n = (this.variables || []).length;
            if (!n) return 'No fields found';
            if (n > 25) return `Search ${n} fields…`;
            return 'Search or pick a field…';
        },

        openVarPicker() {
            if (!this.mailModel || this.variablesLoading) return;
            this.varPickerOpen = true;
            this.varCursor = 0;
        },

        closeVarPicker() {
            this.varPickerOpen = false;
        },

        moveVarCursor(delta) {
            if (!this.varPickerOpen) {
                this.openVarPicker();
                return;
            }
            const max = this.filteredVarOptions().length - 1;
            if (max < 0) return;
            this.varCursor = Math.max(0, Math.min(max, this.varCursor + delta));
        },

        pickVarAtCursor() {
            const opt = this.filteredVarOptions()[this.varCursor];
            if (opt) this.pickVar(opt);
        },

        pickVar(opt) {
            if (!opt?.item) return;
            this.insertVariable(opt.item);
            this.varQuery = '';
            this.closeVarPicker();
            this.$nextTick(() => this.$refs.varInput?.blur());
        },

        async loadVariables() {
            if (this.readonly) return;
            if (!this.mailModel) {
                this.variables = [];
                return;
            }
            this.variablesLoading = true;
            try {
                const url =
                    '/api/mail/templates/variables?model=' +
                    encodeURIComponent(this.mailModel);
                const r = await fetch(url, { credentials: 'same-origin' });
                this.variables = r.ok ? (await r.json()).variables || [] : [];
            } catch (err) {
                console.warn('[pvHtmlEditor] variables load failed', err);
                this.variables = [];
            } finally {
                this.variablesLoading = false;
            }
        },

        insertVariable(item) {
            if (!item?.expr) return;
            const snippet = item.snippet || `{{ ${item.expr} }}`;
            // The picker is only shown on the source tab now, so this is
            // primarily a CodeMirror insert. We keep the TipTap branch as
            // a defensive fallback for callers that synthesize an insert.
            const code = this._codeView();
            if (this.tab === 'source' && code) {
                const pos = code.state.selection.main.head;
                code.dispatch({
                    changes: { from: pos, insert: snippet },
                    selection: { anchor: pos + snippet.length },
                });
                this.html = code.state.doc.toString();
                code.focus();
                return;
            }
            const ed = this._tipTap();
            if (ed && !ed.isDestroyed) {
                ed.chain().focus().insertContent(snippet).run();
                this.html = ed.getHTML();
            } else {
                this.html = (this.html || '') + snippet;
            }
        },

        // --- tab switching ---

        setTab(name) {
            if (this.readonly || this.tab === name) return;
            // Capture the current tab's content BEFORE changing tabs so
            // the destination editor gets the fresh value.
            this.syncAll();
            const prev = this.tab;
            this.tab = name;
            // Picker only makes sense on Source; close it on any other tab.
            if (name !== 'source') this.closeVarPicker();
            this.$nextTick(() => {
                whenVisible(() => {
                    if (name === 'write') this.ensureWrite(prev);
                    if (name === 'source') this.ensureSource(prev);
                });
            });
        },

        ensureWrite(prevTab) {
            if (this.readonly) return;
            const mount = this.$refs.writeMount;
            if (!mount) return;
            let ed = this._tipTap();
            if (!ed || ed.isDestroyed) {
                try {
                    ed = createTipTap(mount, {
                        content: this.html,
                        onUpdate: (v) => {
                            this.html = v;
                        },
                    });
                    this._setTipTap(ed);
                } catch (err) {
                    console.error('[pvHtmlEditor] TipTap mount failed', err);
                }
                return;
            }
            // Existing editor: if we just came from Source/Preview, push
            // `this.html` into TipTap so source-tab edits land in Write too.
            if (prevTab && prevTab !== 'write') {
                const current = ed.getHTML();
                if (current !== this.html) {
                    ed.commands.setContent(this.html || '<p></p>', false);
                }
            }
        },

        ensureSource(prevTab) {
            if (this.readonly) return;
            const mount = this.$refs.sourceMount;
            if (!mount) return;
            let view = this._codeView();
            if (!view) {
                try {
                    view = createCodeMirror(mount, {
                        content: this.html,
                        onUpdate: (v) => {
                            this.html = v;
                        },
                        getCompletions: () => this.variables,
                    });
                    this._setCodeView(view);
                } catch (err) {
                    console.error('[pvHtmlEditor] CodeMirror mount failed', err);
                }
                return;
            }
            if (prevTab && prevTab !== 'source') {
                const current = view.state.doc.toString();
                if (current !== this.html) {
                    view.dispatch({
                        changes: {
                            from: 0,
                            to: current.length,
                            insert: this.html || '',
                        },
                    });
                }
            }
        },

        // --- value sync ---

        syncAll() {
            // Read from whichever editor owns the active tab so source-tab
            // edits don't get overwritten with stale Write HTML on submit.
            const tt = this._tipTap();
            const cv = this._codeView();
            if (this.tab === 'source' && cv) {
                this.html = cv.state.doc.toString();
            } else if (tt && !tt.isDestroyed) {
                this.html = tt.getHTML();
            } else if (cv) {
                this.html = cv.state.doc.toString();
            }
        },

        // --- toolbar ---

        run(cmd) {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            const map = {
                bold: (c) => c.toggleBold(),
                italic: (c) => c.toggleItalic(),
                strike: (c) => c.toggleStrike(),
                h1: (c) => c.toggleHeading({ level: 1 }),
                h2: (c) => c.toggleHeading({ level: 2 }),
                bullet: (c) => c.toggleBulletList(),
                ordered: (c) => c.toggleOrderedList(),
                blockquote: (c) => c.toggleBlockquote(),
                undo: (c) => c.undo(),
                redo: (c) => c.redo(),
                clear: (c) => c.clearNodes().unsetAllMarks(),
            };
            const op = map[cmd];
            if (!op) return;
            try {
                op(ed.chain().focus()).run();
            } catch (err) {
                console.warn('[pvHtmlEditor] toolbar command failed', cmd, err);
                return;
            }
            this.html = ed.getHTML();
        },

        insertLink() {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            const url = window.prompt('Link URL', 'https://');
            if (!url) return;
            try {
                ed.chain()
                    .focus()
                    .extendMarkRange('link')
                    .setLink({ href: url })
                    .run();
            } catch (err) {
                console.warn('[pvHtmlEditor] insertLink failed', err);
                return;
            }
            this.html = ed.getHTML();
        },

        previewHtml() {
            const raw =
                this.html?.trim() ||
                '<p style="color:#6b7280;font-style:italic">(empty)</p>';
            return stripScripts(raw);
        },

        destroy() {
            const eds = EDITORS.get(this.$root);
            if (!eds) return;
            destroyEditor(eds.tipTap);
            destroyEditor(eds.codeView);
            EDITORS.delete(this.$root);
        },
    }));
}

function syncBeforeSubmit() {
    document.querySelectorAll('.pv-html-editor').forEach((el) => {
        const cmp = window.Alpine?.$data(el);
        if (cmp?.syncAll) cmp.syncAll();
    });
}

function wireHtmx() {
    if (!document.body) return;
    // The visible textarea is a hidden mirror of `this.html`, so we sync it
    // once before each HTMX submit. Alpine's own mutation observer wires
    // fresh x-data nodes inserted via HTMX — no explicit initTree() call.
    document.body.addEventListener('htmx:beforeRequest', syncBeforeSubmit);
}

function boot() {
    const register = () => {
        if (window.__pvHtmlEditorRegistered) return;
        registerAlpine();
        window.__pvHtmlEditorRegistered = true;
    };
    document.addEventListener('alpine:init', register);
    if (document.body) wireHtmx();
    else document.addEventListener('DOMContentLoaded', wireHtmx);
}

boot();
