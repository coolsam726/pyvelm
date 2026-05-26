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
import { TextStyle } from '@tiptap/extension-text-style';
import { Color } from '@tiptap/extension-color';
import { Highlight } from '@tiptap/extension-highlight';
import { TextAlign } from '@tiptap/extension-text-align';
import { Image } from '@tiptap/extension-image';
import { TaskList } from '@tiptap/extension-task-list';
import { TaskItem } from '@tiptap/extension-task-item';
import { Placeholder } from '@tiptap/extension-placeholder';
import {
    applyFormatToView,
    buildCodeView,
    formatSource,
    getDocContent,
    htmlLooksMinified,
    jinjaTemplateCompletions,
    reconfigureLanguage,
    reconfigureTheme,
    setDocContent,
} from './codemirror_field.js';

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

function createTipTap(mountEl, { content, onUpdate, onSelectionChange }) {
    mountEl.innerHTML = '';
    const initial = content?.trim() ? content : '<p></p>';
    const editor = new Editor({
        element: mountEl,
        // Extension set matches TipTap's Simple Editor template. StarterKit
        // v3 already bundles Bold/Italic/Underline/Strike/Code/Link/Heading/
        // Lists/Blockquote/CodeBlock/HorizontalRule/Undo-Redo, so we only
        // import the extras Simple Editor pulls in on top of it.
        extensions: [
            StarterKit.configure({
                heading: { levels: [1, 2, 3, 4] },
                link: {
                    openOnClick: false,
                    HTMLAttributes: { rel: 'noopener noreferrer' },
                },
            }),
            TextStyle,
            Color,
            Highlight.configure({ multicolor: true }),
            TextAlign.configure({
                types: ['heading', 'paragraph'],
                alignments: ['left', 'center', 'right', 'justify'],
            }),
            Image.configure({ inline: false, allowBase64: false }),
            TaskList,
            TaskItem.configure({ nested: true }),
            Placeholder.configure({
                placeholder: 'Start writing your email…',
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
        // Selection moves don't change `getHTML()`, but the toolbar's
        // active states (which mark is at the cursor?) need refreshing.
        // Bump a reactive counter so Alpine re-evaluates :class bindings.
        onSelectionUpdate: () => onSelectionChange?.(),
        onTransaction: () => onSelectionChange?.(),
    });
    whenVisible(() => {
        if (!editor.isDestroyed) editor.commands.focus('end');
    });
    return editor;
}

function registerAlpine() {
    if (!window.Alpine) {
        console.error('[pvHtmlEditor] Alpine.js not found');
        return;
    }

    window.Alpine.data('pvHtmlEditor', () => ({
        // --- config (filled in by init() from data-pv-config) ---
        name: 'body_html',
        sourceLanguage: 'html',
        readonly: false,
        mailModel: '',
        // Stored subject from the record. Edit mode reads the live form
        // input instead; display mode uses this since no input exists.
        subject: '',

        // --- reactive model state ---
        html: '',
        tab: 'write',
        // Bumped on every TipTap selection / transaction so :class
        // bindings that call `isActive()` re-evaluate.
        _selVersion: 0,
        variables: [],
        variablesLoading: false,
        varQuery: '',
        varPickerOpen: false,
        varCursor: 0,
        sourceCopied: false,
        sourceFormatError: '',
        _sourceAutoFormatted: false,

        // --- live-preview state (Preview tab only) ---
        previewQuery: '',
        previewPickerOpen: false,
        previewLoading: false,
        previewResults: [],
        previewRecord: null, // {id, label} when a sample record is chosen
        previewRendering: false,
        previewRendered: null, // {subject, body_html, res_id} once rendered
        previewError: '',
        _previewSeq: 0, // monotonic to drop stale fetches

        // NOTE: there is no `tipTap` / `codeView` property here on purpose.
        // The instances live in the module-level EDITORS WeakMap so Alpine
        // doesn't proxy them. See the module-level comment above.

        init() {
            const cfg = parseConfig(this.$root);
            this.name = cfg.name || 'body_html';
            this.html = cfg.initial ?? '';
            this.readonly = !!cfg.readonly;
            this.tab = this.readonly ? 'preview' : 'write';
            this.sourceLanguage = 'html';
            this.mailModel = cfg.mailModel || '';
            this.subject = cfg.subject || '';

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
                        // Live-preview state is model-scoped; reset it so
                        // the user doesn't try to render template-A's body
                        // against model-B's record.
                        this.previewRecord = null;
                        this.previewResults = [];
                        this.previewQuery = '';
                        this.previewRendered = null;
                        this.previewError = '';
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
            } else if (this.mailModel) {
                // Display mode lands directly on the Preview panel — render
                // the stored body against the first available record so
                // the user sees the live preview without an extra click.
                this.$nextTick(() => this.renderPreview());
            }

            this._themeObserver = new MutationObserver(() => {
                reconfigureTheme(this._codeView());
            });
            this._themeObserver.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['class'],
            });
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

        // --- live preview (Preview tab) ---

        openPreviewPicker() {
            if (!this.mailModel) return;
            this.previewPickerOpen = true;
            // Kick off an initial empty-query search so the user sees
            // the first N records without having to type.
            if (this.previewResults.length === 0 && !this.previewLoading) {
                this.searchPreviewRecords();
            }
        },

        async searchPreviewRecords() {
            if (!this.mailModel) {
                this.previewResults = [];
                return;
            }
            const seq = ++this._previewSeq;
            this.previewLoading = true;
            try {
                const params = new URLSearchParams({
                    model: this.mailModel,
                    q: this.previewQuery || '',
                    limit: '20',
                });
                const r = await fetch('/api/m2o/search?' + params, {
                    credentials: 'same-origin',
                });
                if (seq !== this._previewSeq) return; // a newer query won
                this.previewResults = r.ok
                    ? (await r.json()).results || []
                    : [];
                this.previewPickerOpen = true;
            } catch (err) {
                if (seq === this._previewSeq) this.previewResults = [];
            } finally {
                if (seq === this._previewSeq) this.previewLoading = false;
            }
        },

        pickPreviewRecord(r) {
            this.previewRecord = r;
            this.previewQuery = '';
            this.previewPickerOpen = false;
            // Auto-render on pick — that's the whole point of choosing.
            this.renderPreview();
        },

        clearPreviewRecord() {
            this.previewRecord = null;
            this.previewQuery = '';
            this.previewRendered = null;
            this.previewError = '';
        },

        _readSubject() {
            // Edit mode: read the live form input so the latest edit
            // shows in the preview. Display mode: no input exists, so
            // fall back to the value the server stamped into cfg.
            const form = this.$root.closest('form');
            if (form) {
                const el = form.querySelector('input[name="subject"]');
                if (el) return el.value || '';
            }
            return this.subject || '';
        },

        _csrfHeader() {
            // The framework's CSRF middleware accepts an X-CSRF-Token
            // header on unsafe methods. `window.pvCsrf` is wired in
            // layouts/main.html; missing means cookie-less request, which
            // the middleware exempts (so no header is fine).
            try {
                return typeof window.pvCsrf === 'function'
                    ? window.pvCsrf()
                    : '';
            } catch {
                return '';
            }
        },

        async renderPreview() {
            if (!this.mailModel) {
                this.previewError = 'Pick a model on the form first.';
                return;
            }
            // Make sure the active editor's contents are mirrored into
            // `this.html` before we ship the draft.
            this.syncAll();
            this.previewRendering = true;
            this.previewError = '';
            try {
                const headers = {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                };
                const csrf = this._csrfHeader();
                if (csrf) headers['X-CSRF-Token'] = csrf;
                const r = await fetch('/api/mail/templates/preview', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers,
                    body: JSON.stringify({
                        model: this.mailModel,
                        subject: this._readSubject(),
                        body_html: this.html,
                        res_id: this.previewRecord?.id ?? null,
                    }),
                });
                if (!r.ok) {
                    let detail = '';
                    try {
                        detail = (await r.json()).detail || '';
                    } catch {
                        detail = await r.text();
                    }
                    this.previewError =
                        detail || `Render failed (HTTP ${r.status})`;
                    this.previewRendered = null;
                    return;
                }
                this.previewRendered = await r.json();
            } catch (err) {
                this.previewError =
                    err && err.message ? err.message : 'Render failed';
                this.previewRendered = null;
            } finally {
                this.previewRendering = false;
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
                this.html = getDocContent(code);
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
            // Auto-render the Preview tab once a model is available, so
            // the admin lands on a real rendering rather than the raw
            // client-side fallback.
            if (name === 'preview' && this.mailModel) {
                this.renderPreview();
            }
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
                        onSelectionChange: () => {
                            this._selVersion++;
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
                    let initial = this.html;
                    if (
                        !this._sourceAutoFormatted &&
                        htmlLooksMinified(initial)
                    ) {
                        const formatted = formatSource(initial, 'html');
                        if (formatted !== null) {
                            initial = formatted;
                            this.html = initial;
                        }
                        this._sourceAutoFormatted = true;
                    }
                    view = buildCodeView(mount, {
                        content: initial,
                        language: this.sourceLanguage,
                        readonly: false,
                        onUpdate: (v) => {
                            this.html = v;
                        },
                        extraExtensions: [
                            jinjaTemplateCompletions(() => this.variables),
                        ],
                    });
                    this._setCodeView(view);
                    reconfigureTheme(view);
                    whenVisible(() => {
                        view.requestMeasure();
                        view.focus();
                    });
                } catch (err) {
                    console.error('[pvHtmlEditor] CodeMirror mount failed', err);
                }
                return;
            }
            if (prevTab && prevTab !== 'source') {
                if (htmlLooksMinified(this.html)) {
                    const formatted = formatSource(this.html, 'html');
                    if (formatted !== null) {
                        this.html = formatted;
                    }
                }
                setDocContent(view, this.html);
            }
        },

        applySourceLanguage() {
            const lang = this.sourceLanguage === 'jinja' ? 'jinja' : 'html';
            const view = this._codeView();
            if (view) reconfigureLanguage(view, lang);
        },

        formatSourceHtml() {
            this.sourceFormatError = '';
            this.syncAll();
            const view = this._codeView();
            if (!view) return;
            const fmtLang =
                this.sourceLanguage === 'jinja' ? 'html' : this.sourceLanguage;
            const after = applyFormatToView(view, fmtLang, (v) => {
                this.html = v;
            });
            if (after === null) {
                this.sourceFormatError = 'Could not format';
                setTimeout(() => {
                    this.sourceFormatError = '';
                }, 2500);
            }
        },

        async copySource() {
            this.syncAll();
            try {
                await navigator.clipboard.writeText(this.html || '');
                this.sourceCopied = true;
                setTimeout(() => {
                    this.sourceCopied = false;
                }, 1500);
            } catch (err) {
                console.warn('[pvHtmlEditor] copy failed', err);
            }
        },

        // --- value sync ---

        syncAll() {
            // Read from whichever editor owns the active tab so source-tab
            // edits don't get overwritten with stale Write HTML on submit.
            const tt = this._tipTap();
            const cv = this._codeView();
            if (this.tab === 'source' && cv) {
                this.html = getDocContent(cv);
            } else if (tt && !tt.isDestroyed) {
                this.html = tt.getHTML();
            } else if (cv) {
                this.html = getDocContent(cv);
            }
        },

        // --- toolbar ---

        // Single string for *which* dropdown / popover is currently open;
        // empty means none. One menu open at a time mirrors the Word
        // ribbon, and the click-outside / setTab close paths only have to
        // touch one variable.
        openDropdown: '',
        // Mirrors the Simple Editor palette: brand colors + warm/cool.
        colorPalette: [
            '#0F172A', '#475569', '#DC2626', '#F97316',
            '#EAB308', '#16A34A', '#0EA5E9', '#7C3AED',
        ],
        highlightPalette: [
            '#FEF08A', '#FECACA', '#BBF7D0', '#BFDBFE',
            '#E9D5FF', '#FBCFE8', '#FED7AA', '#F1F5F9',
        ],
        isImageUploading: false,

        run(cmd, arg) {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            // Each entry returns the chain after applying its command so
            // .run() at the end commits the transaction atomically.
            const map = {
                // marks
                bold: (c) => c.toggleBold(),
                italic: (c) => c.toggleItalic(),
                underline: (c) => c.toggleUnderline(),
                strike: (c) => c.toggleStrike(),
                code: (c) => c.toggleCode(),
                // headings — `arg` is the level (1..4); 0 / undefined = paragraph
                heading: (c) =>
                    arg ? c.toggleHeading({ level: arg }) : c.setParagraph(),
                // lists
                bullet: (c) => c.toggleBulletList(),
                ordered: (c) => c.toggleOrderedList(),
                task: (c) => c.toggleTaskList(),
                // blocks
                blockquote: (c) => c.toggleBlockquote(),
                codeBlock: (c) => c.toggleCodeBlock(),
                hr: (c) => c.setHorizontalRule(),
                // alignment
                alignLeft: (c) => c.setTextAlign('left'),
                alignCenter: (c) => c.setTextAlign('center'),
                alignRight: (c) => c.setTextAlign('right'),
                alignJustify: (c) => c.setTextAlign('justify'),
                // history
                undo: (c) => c.undo(),
                redo: (c) => c.redo(),
                clear: (c) => c.unsetAllMarks().clearNodes(),
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

        // ---- popover commands (color / highlight) ----

        setColor(hex) {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            try {
                ed.chain().focus().setColor(hex).run();
            } catch (err) {
                console.warn('[pvHtmlEditor] setColor failed', err);
            }
            this.openDropdown = '';
            this.html = ed.getHTML();
        },

        unsetColor() {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            ed.chain().focus().unsetColor().run();
            this.openDropdown = '';
            this.html = ed.getHTML();
        },

        setHighlight(hex) {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            try {
                ed.chain().focus().toggleHighlight({ color: hex }).run();
            } catch (err) {
                console.warn('[pvHtmlEditor] setHighlight failed', err);
            }
            this.openDropdown = '';
            this.html = ed.getHTML();
        },

        unsetHighlight() {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            ed.chain().focus().unsetHighlight().run();
            this.openDropdown = '';
            this.html = ed.getHTML();
        },

        // ---- link (kept as a prompt for now; Simple Editor uses a popover,
        // but for an email-template editor a one-tap prompt is plenty) ----

        insertLink() {
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            const current = ed.getAttributes('link')?.href || '';
            const url = window.prompt(
                'Link URL (leave empty to remove)',
                current || 'https://'
            );
            if (url === null) return; // cancelled
            try {
                if (!url.trim()) {
                    ed.chain().focus().extendMarkRange('link').unsetLink().run();
                } else {
                    ed.chain()
                        .focus()
                        .extendMarkRange('link')
                        .setLink({ href: url.trim() })
                        .run();
                }
            } catch (err) {
                console.warn('[pvHtmlEditor] insertLink failed', err);
                return;
            }
            this.html = ed.getHTML();
        },

        // ---- image upload (file picker → POST /api/attachment/upload) ----

        triggerImageUpload() {
            const input = this.$refs.imageFile;
            if (input) {
                input.value = ''; // re-trigger change for the same file
                input.click();
            }
        },

        async handleImageFile(event) {
            const file = event.target?.files?.[0];
            if (!file) return;
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return;
            this.isImageUploading = true;
            try {
                const fd = new FormData();
                fd.append('file', file);
                const headers = {};
                const csrf = this._csrfHeader();
                if (csrf) headers['X-CSRF-Token'] = csrf;
                const r = await fetch('/api/attachment/upload', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers,
                    body: fd,
                });
                if (!r.ok) {
                    console.warn(
                        '[pvHtmlEditor] image upload failed',
                        r.status
                    );
                    return;
                }
                const data = await r.json();
                const src = `/api/attachment/${data.id}/download`;
                ed.chain()
                    .focus()
                    .setImage({ src, alt: data.name || '' })
                    .run();
                this.html = ed.getHTML();
            } catch (err) {
                console.warn('[pvHtmlEditor] image upload error', err);
            } finally {
                this.isImageUploading = false;
            }
        },

        // ---- state queries used by the toolbar's :class bindings ----

        isActive(name, attrs) {
            // Touch the reactive counter so Alpine re-runs this expression
            // whenever the cursor / selection moves (otherwise the toolbar
            // would only update when `this.html` changes, missing typing
            // and arrow-key moves).
            void this._selVersion;
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return false;
            try {
                return ed.isActive(name, attrs);
            } catch {
                return false;
            }
        },

        currentHeadingLevel() {
            void this._selVersion;
            const ed = this._tipTap();
            if (!ed || ed.isDestroyed) return 0;
            for (const level of [1, 2, 3, 4]) {
                if (ed.isActive('heading', { level })) return level;
            }
            return 0;
        },

        currentHeadingLabel() {
            const lv = this.currentHeadingLevel();
            return lv === 0 ? 'Normal text' : `Heading ${lv}`;
        },

        currentAlignLabel() {
            if (this.isActive({ textAlign: 'center' })) return 'Center';
            if (this.isActive({ textAlign: 'right' })) return 'Right';
            if (this.isActive({ textAlign: 'justify' })) return 'Justify';
            return 'Left';
        },

        currentListLabel() {
            if (this.isActive('orderedList')) return 'Numbered';
            if (this.isActive('taskList')) return 'Checklist';
            if (this.isActive('bulletList')) return 'Bulleted';
            return 'List';
        },

        // Ribbon dropdown plumbing — one menu open at a time.
        toggleDropdown(name) {
            this.openDropdown = this.openDropdown === name ? '' : name;
        },

        closeDropdowns() {
            this.openDropdown = '';
        },

        // Fire a toolbar command AND close any open dropdown — used by
        // the menu options so picking a heading / list / alignment
        // dismisses the menu without an extra click.
        runFromMenu(cmd, arg) {
            this.run(cmd, arg);
            this.openDropdown = '';
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
            if (this._themeObserver) {
                this._themeObserver.disconnect();
                this._themeObserver = null;
            }
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
