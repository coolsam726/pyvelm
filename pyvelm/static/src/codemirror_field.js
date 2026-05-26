/**
 * Shared CodeMirror 6 field builder (used by pvCodeEditor and pvHtmlEditor).
 */
import { EditorState, Compartment } from '@codemirror/state';
import {
    EditorView,
    keymap,
    lineNumbers,
    highlightActiveLine,
    highlightActiveLineGutter,
    drawSelection,
} from '@codemirror/view';
import {
    defaultKeymap,
    history,
    historyKeymap,
    indentWithTab,
} from '@codemirror/commands';
import {
    StreamLanguage,
    bracketMatching,
    foldGutter,
    foldKeymap,
    indentOnInput,
    indentUnit,
} from '@codemirror/language';
import { jinja2 } from '@codemirror/legacy-modes/mode/jinja2';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import {
    autocompletion,
    closeBrackets,
    closeBracketsKeymap,
    completionKeymap,
    completeFromList,
} from '@codemirror/autocomplete';
import { vscodeDark, vscodeLight } from '@uiw/codemirror-theme-vscode';

import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { css } from '@codemirror/lang-css';
import { json } from '@codemirror/lang-json';
import { sql } from '@codemirror/lang-sql';
import { xml } from '@codemirror/lang-xml';
import { markdown } from '@codemirror/lang-markdown';
import { html as langHtml } from '@codemirror/lang-html';
import beautify from 'js-beautify';

const htmlBeautify = beautify.html;
const cssBeautify = beautify.css;
const jsBeautify = beautify.js;

export function languageExtension(lang) {
    switch ((lang || 'text').toLowerCase()) {
        case 'javascript':
            return javascript({ jsx: true });
        case 'typescript':
            return javascript({ jsx: true, typescript: true });
        case 'python':
            return python();
        case 'css':
            return css();
        case 'json':
            return json();
        case 'sql':
            return sql();
        case 'xml':
            return xml();
        case 'markdown':
            return markdown();
        case 'html':
            return langHtml();
        case 'jinja':
            return StreamLanguage.define(jinja2);
        case 'text':
        default:
            return [];
    }
}

export function isDarkMode() {
    return document.documentElement.classList.contains('dark');
}

export function pickTheme() {
    return isDarkMode() ? vscodeDark : vscodeLight;
}

/** Jinja placeholder autocomplete for mail templates. */
export function jinjaTemplateCompletions(getCompletions) {
    return autocompletion({
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
            completeFromList(
                (getCompletions?.() || []).map((v) => ({
                    label: v.expr,
                    detail: v.label,
                    type: 'variable',
                    apply: v.snippet || `{{ ${v.expr} }}`,
                }))
            ),
        ],
    });
}

/**
 * Mount a VSCode-themed CodeMirror instance (same stack as the Code field widget).
 */
export function buildCodeView(mountEl, {
    content,
    language = 'text',
    readonly = false,
    onUpdate,
    extraExtensions = [],
}) {
    mountEl.innerHTML = '';
    const langCompartment = new Compartment();
    const themeCompartment = new Compartment();
    const editableCompartment = new Compartment();

    const state = EditorState.create({
        doc: content ?? '',
        extensions: [
            lineNumbers(),
            highlightActiveLine(),
            highlightActiveLineGutter(),
            foldGutter(),
            drawSelection(),
            history(),
            bracketMatching(),
            closeBrackets(),
            indentOnInput(),
            indentUnit.of('    '),
            EditorView.lineWrapping,
            highlightSelectionMatches(),
            langCompartment.of(languageExtension(language)),
            themeCompartment.of(pickTheme()),
            editableCompartment.of(EditorView.editable.of(!readonly)),
            keymap.of([
                ...closeBracketsKeymap,
                ...defaultKeymap,
                ...searchKeymap,
                ...historyKeymap,
                ...foldKeymap,
                ...completionKeymap,
                indentWithTab,
            ]),
            ...extraExtensions,
            EditorView.updateListener.of((update) => {
                if (update.docChanged && onUpdate) {
                    onUpdate(update.state.doc.toString());
                }
            }),
        ],
    });
    const view = new EditorView({ state, parent: mountEl });
    view._pvCompartments = {
        lang: langCompartment,
        theme: themeCompartment,
        editable: editableCompartment,
    };
    return view;
}

export function reconfigureTheme(view) {
    if (!view?._pvCompartments?.theme) return;
    view.dispatch({
        effects: view._pvCompartments.theme.reconfigure(pickTheme()),
    });
}

export function reconfigureLanguage(view, language) {
    if (!view?._pvCompartments?.lang) return;
    view.dispatch({
        effects: view._pvCompartments.lang.reconfigure(
            languageExtension(language)
        ),
    });
}

export function setDocContent(view, text) {
    if (!view) return;
    const current = view.state.doc.toString();
    const next = text ?? '';
    if (current === next) return;
    view.dispatch({
        changes: { from: 0, to: current.length, insert: next },
    });
}

export function getDocContent(view) {
    return view ? view.state.doc.toString() : '';
}

const FORMAT_BASE = {
    indent_size: 2,
    indent_char: ' ',
    end_with_newline: true,
    preserve_newlines: true,
    max_preserve_newlines: 2,
    wrap_line_length: 0,
};

const FORMATTABLE = new Set([
    'html',
    'xml',
    'css',
    'javascript',
    'typescript',
    'json',
]);

export function canFormatLanguage(language) {
    return FORMATTABLE.has((language || 'text').toLowerCase());
}

/** True when HTML is likely one long line from TipTap export. */
export function htmlLooksMinified(code) {
    const s = (code || '').trim();
    if (!s || s.length < 80) return false;
    return (s.match(/\n/g) || []).length <= 1;
}

const HTML_FORMAT_OPTS = {
    ...FORMAT_BASE,
    indent_inner_html: true,
    indent_body_inner_html: true,
    templating: ['django', 'handlebars', 'angular'],
};

/** Email bodies are HTML fragments — wrap so the beautifier can indent them. */
function formatHtmlFragment(src) {
    const trimmed = src.trim();
    if (!trimmed) return trimmed;
    if (!htmlBeautify) {
        throw new Error('html beautifier unavailable');
    }
    const wrapped = `<html><body>\n${trimmed}\n</body></html>`;
    const out = htmlBeautify(wrapped, HTML_FORMAT_OPTS);
    const match = out.match(/<body[^>]*>\n?([\s\S]*?)\n?\s*<\/body>/i);
    if (match) {
        const body = match[1].replace(/^\s{4}/gm, '').replace(/\s+$/, '');
        return body ? `${body}\n` : '\n';
    }
    return htmlBeautify(trimmed, HTML_FORMAT_OPTS);
}

/**
 * Pretty-print source. Returns `null` on failure; otherwise the formatted
 * text (may match input when already tidy).
 */
export function formatSource(code, language) {
    const src = code ?? '';
    if (!src.trim()) return src;
    const lang = (language || 'text').toLowerCase();
    try {
        if (lang === 'html' || lang === 'xml') {
            return formatHtmlFragment(src);
        }
        if (lang === 'css') {
            return cssBeautify(src, FORMAT_BASE);
        }
        if (lang === 'javascript' || lang === 'typescript') {
            return jsBeautify(src, { ...FORMAT_BASE, e4x: true });
        }
        if (lang === 'json') {
            return `${JSON.stringify(JSON.parse(src), null, 2)}\n`;
        }
    } catch (err) {
        console.warn('[codemirror_field] format failed', err);
        return null;
    }
    return src;
}

/**
 * Replace the editor document with formatted text.
 * Returns `null` if formatting failed; otherwise the new document string.
 */
export function applyFormatToView(view, language, onUpdate) {
    if (!view || !canFormatLanguage(language)) {
        return getDocContent(view);
    }
    const formatted = formatSource(getDocContent(view), language);
    if (formatted === null) {
        return null;
    }
    setDocContent(view, formatted);
    if (onUpdate) onUpdate(formatted);
    return formatted;
}
