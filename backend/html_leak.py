"""Keep raw HTML/CSS out of prompts and out of the article body.

Workspace files (``cta_guidelines.md``, ``writing_guidelines.md``) may hold HTML
snippets: a CTA shell, a styled table preview, a full ``<!doctype html>`` demo
page. Those are meant for post-processing and for human editors, not for the
model. When they are pasted into the system prompt the model copies them into
the article, which breaks the markdown, inflates the word count (CSS counts as
words), and makes the article look like a code dump.

Two safety layers live here:

* :func:`strip_html_for_prompt` removes HTML/CSS from context text before it is
  sent to the model (the pipeline still reads the raw file for the CTA shell).
* :func:`strip_leaked_html` repairs an article the model already polluted:
  leaked tables become markdown tables, leaked CTA shells become markdown CTAs
  (the pipeline re-wraps those in the workspace HTML at the very end), and
  everything else (doctype pages, ``<style>`` blocks, template labels) is dropped.
"""

from __future__ import annotations

import html as html_lib
import re

_DOCTYPE_RE = re.compile(r"(?is)<!doctype\b[^>]*>[\s\S]*?</html\s*>")
_DOCTYPE_NO_CLOSE_RE = re.compile(r"(?is)<!doctype\b[^>]*>[\s\S]*?</body\s*>")
_STRAY_DOC_TAG_RE = re.compile(r"(?i)</?(?:html|head|body)\b[^>]*>|<!doctype\b[^>]*>")
_STYLE_RE = re.compile(r"(?is)<style\b[^>]*>[\s\S]*?</style\s*>")
_SCRIPT_RE = re.compile(r"(?is)<script\b(?![^>]*ld\+json)[^>]*>[\s\S]*?</script\s*>")
_TABLE_RE = re.compile(r"(?is)<table\b[^>]*>[\s\S]*?</table\s*>")
_ROW_RE = re.compile(r"(?is)<tr\b[^>]*>([\s\S]*?)</tr\s*>")
_CELL_RE = re.compile(r"(?is)<(t[hd])\b[^>]*>([\s\S]*?)</t[hd]\s*>")
_TAG_RE = re.compile(r"(?s)</?[a-zA-Z][^>]*>")
_FENCED_HTML_RE = re.compile(r"(?is)```[ \t]*(?:html|css)[ \t]*\n[\s\S]*?```")
_TEMPLATE_LABEL_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?[ \t]*HTML[ \t]+CTA[ \t]+Template[ \t]*:?[ \t]*(?:\*\*)?[ \t]*\n?"
)
_CTA_DIV_OPEN_RE = re.compile(
    r"(?is)<div\b[^>]*\bclass\s*=\s*[\"'][^\"']*cta[^\"']*[\"'][^>]*>"
)
_DIV_TOKEN_RE = re.compile(r"(?i)<(/?)div\b[^>]*>")
_H3_RE = re.compile(r"(?is)<h3\b[^>]*>([\s\S]*?)</h3\s*>")
_P_RE = re.compile(r"(?is)<p\b[^>]*>([\s\S]*?)</p\s*>")
_A_RE = re.compile(r"(?is)<a\b[^>]*\bhref\s*=\s*([\"'])([^\"']*)\1[^>]*>([\s\S]*?)</a\s*>")
_MD_BOLD_LINE_RE = re.compile(r"^[ \t]*\*\*[^*\n][^\n*]*\*\*[ \t]*$")
_MD_LINK_LINE_RE = re.compile(r"^[ \t]*\[[^\]]{1,120}\]\([^)\s]+\)[ \t]*$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}\}")
_BLANKS_RE = re.compile(r"\n{3,}")

# Section heading that introduces the HTML shell inside cta_guidelines.md.
_HTML_SECTION_RE = re.compile(
    r"(?is)(?:^|\n)(#{2,4}[ \t]*HTML[ \t]+CTA[ \t]+Template[ \t]*\n[\s\S]*?)(?=\n#{1,4}[ \t]+\S|\Z)"
)

_PROMPT_NOTE = (
    "[HTML/CSS snippet omitted from the prompt. Do not write HTML, CSS or table "
    "markup. Write markdown only: CTAs as bold heading + description + markdown link, "
    "tables as markdown pipe tables. The pipeline applies the HTML shell afterwards.]"
)


# --------------------------------------------------------------------------- #
# Prompt side
# --------------------------------------------------------------------------- #


def _remove_balanced(text: str, tag: str) -> str:
    """Remove ``<tag ...>...</tag>`` blocks, honouring nesting of the same tag."""
    open_re = re.compile(rf"(?i)<{tag}\b[^>]*>")
    token_re = re.compile(rf"(?i)<(/?){tag}\b[^>]*>")
    out: list[str] = []
    pos = 0
    while True:
        m = open_re.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        depth = 0
        end = None
        for t in token_re.finditer(text, m.start()):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = t.end()
                break
        if end is None:  # unbalanced: drop nothing, keep the rest as-is
            out.append(text[pos:])
            break
        out.append(text[pos : m.start()])
        out.append(_PROMPT_NOTE)
        pos = end
    return "".join(out)


def strip_html_for_prompt(text: str) -> str:
    """Drop HTML/CSS from context-file text that is destined for an LLM prompt."""
    if not text or "<" not in text:
        return text
    out = text

    # The whole "HTML CTA Template" section is an editor/pipeline artefact.
    out = _HTML_SECTION_RE.sub(lambda m: "\n" + _PROMPT_NOTE + "\n", out)
    out = _FENCED_HTML_RE.sub(_PROMPT_NOTE, out)
    out = _DOCTYPE_RE.sub(_PROMPT_NOTE, out)
    out = _STYLE_RE.sub("", out)
    out = _SCRIPT_RE.sub("", out)
    for tag in ("table", "div", "section"):
        out = _remove_balanced(out, tag)

    # Collapse repeated notes and blank runs left behind.
    out = re.sub(
        rf"(?:{re.escape(_PROMPT_NOTE)}\s*){{2,}}", _PROMPT_NOTE + "\n", out
    )
    return _BLANKS_RE.sub("\n\n", out)


# --------------------------------------------------------------------------- #
# Article side
# --------------------------------------------------------------------------- #


def _plain(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def html_table_to_markdown(table_html: str) -> str:
    """Convert one ``<table>`` to a markdown pipe table ('' when unusable)."""
    rows: list[list[str]] = []
    header_row = False
    for i, rm in enumerate(_ROW_RE.finditer(table_html)):
        cells = _CELL_RE.findall(rm.group(1))
        if not cells:
            continue
        if i == 0 and all(kind.lower() == "th" for kind, _ in cells):
            header_row = True
        rows.append([_plain(c).replace("|", "\\|") for _, c in cells])
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = rows[0]
    body = rows[1:]
    if not header_row and not body:
        return ""
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _tables_to_markdown(text: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        md = html_table_to_markdown(m.group(0))
        return f"\n\n{md}\n\n" if md else ""

    return _TABLE_RE.sub(_sub, text)


def _find_div_end(text: str, start: int) -> int | None:
    depth = 0
    for t in _DIV_TOKEN_RE.finditer(text, start):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return t.end()
    return None


def _tail_state(prefix: str) -> str:
    """Classify the text right before a leaked CTA shell.

    ``complete``: ends with a markdown CTA (bold, body, link line).
    ``orphan``:   bold heading + body but no link line.
    ``none``:     no CTA copy precedes it.
    """
    lines = prefix.rstrip().split("\n")
    if not lines or not lines[-1].strip():
        return "none"
    if _MD_LINK_LINE_RE.match(lines[-1]):
        return "complete"
    seen = 0
    for ln in reversed(lines):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("!["):
            return "none"
        if _MD_BOLD_LINE_RE.match(ln):
            return "orphan" if seen >= 1 else "none"
        seen += 1
        if seen > 5:
            return "none"
    return "none"


def _cta_fields(block: str) -> tuple[str, str, str, str]:
    h3 = _H3_RE.search(block)
    p = _P_RE.search(block)
    a = _A_RE.search(block)
    headline = _plain(h3.group(1)) if h3 else ""
    body = _plain(p.group(1)) if p else ""
    href = (a.group(2) if a else "").strip()
    label = _plain(a.group(3)) if a else ""
    label = re.sub(r"[\s\u2197\u2192\u279c>]+$", "", label).strip()
    return headline, body, label, href


def _leaked_cta_to_markdown(text: str, cta_href: str | None) -> str:
    """Replace leaked CTA ``<div>`` shells (and their CSS) with markdown CTAs."""
    default_href = (cta_href or "").strip() or "/contact"
    out = text
    guard = 0
    while guard < 20:
        guard += 1
        m = _CTA_DIV_OPEN_RE.search(out)
        if not m:
            break
        end = _find_div_end(out, m.start())
        if end is None:
            out = out[: m.start()] + out[m.end() :]
            continue
        block = out[m.start() : end]
        prefix, rest = out[: m.start()], out[end:]
        headline, body, label, href = _cta_fields(block)
        href = default_href if (not href or "{{" in href) else href
        label = label or "Talk to our team"
        is_template = bool(_PLACEHOLDER_RE.search(block))

        replacement = ""
        if not is_template:
            state = _tail_state(prefix)
            if state == "orphan":
                replacement = f"\n\n[{label}]({href})\n\n"
            elif state == "none" and headline and body:
                replacement = f"\n\n**{headline}**\n\n{body}\n\n[{label}]({href})\n\n"
        out = prefix.rstrip("\n") + replacement + rest.lstrip("\n")

    # CTA CSS left behind (the pipeline re-adds it when it wraps the CTAs).
    def _drop_cta_style(m: re.Match[str]) -> str:
        return "" if "cta" in m.group(0).lower() else m.group(0)

    return _STYLE_RE.sub(_drop_cta_style, out)


_FENCE_START_RE = re.compile(r"^[ \t]*```")
_HTML_START_RE = re.compile(r"(?is)^\s*<(?:div|style|section|table|!doctype|html)\b")


def unwrap_html_fences(text: str) -> str:
    """Remove ``` fences that wrap HTML/CSS so the HTML is not shown as code.

    The preview (and many markdown renderers) turn a fenced block into a code
    block. If a fence opens before a CTA shell and never closes, the rest of the
    article is displayed as raw markdown. Fences around real code are kept.
    """
    if not text or "```" not in text:
        return text
    lines = text.split("\n")
    fence_idx = [i for i, ln in enumerate(lines) if _FENCE_START_RE.match(ln)]
    drop: set[int] = set()
    k = 0
    while k < len(fence_idx):
        i = fence_idx[k]
        j = fence_idx[k + 1] if k + 1 < len(fence_idx) else None
        inner = "\n".join(lines[i + 1 : j]) if j is not None else "\n".join(lines[i + 1 :])
        if _HTML_START_RE.match(inner):
            drop.add(i)
            if j is not None:
                drop.add(j)
            k += 2 if j is not None else 1
        else:
            k += 2 if j is not None else 1
    if not drop:
        return text
    return "\n".join(ln for n, ln in enumerate(lines) if n not in drop)


def has_leaked_html(article: str) -> bool:
    low = (article or "").lower()
    if not low:
        return False
    if "```" in low and unwrap_html_fences(article) != article:
        return True
    return any(
        tok in low for tok in ("<!doctype", "<style", "<table", "html cta template")
    ) or bool(_CTA_DIV_OPEN_RE.search(article))


def strip_leaked_html(article: str, *, cta_href: str | None = None) -> str:
    """Repair an article that contains pasted HTML/CSS templates."""
    if not article or not has_leaked_html(article):
        return article

    out = unwrap_html_fences(article)
    # Tables inside a demo page survive as markdown tables.
    def _doc_sub(m: re.Match[str]) -> str:
        tables = [
            html_table_to_markdown(t.group(0)) for t in _TABLE_RE.finditer(m.group(0))
        ]
        tables = [t for t in tables if t]
        return ("\n\n" + "\n\n".join(tables) + "\n\n") if tables else ""

    out = _DOCTYPE_RE.sub(_doc_sub, out)
    out = _DOCTYPE_NO_CLOSE_RE.sub(_doc_sub, out)
    out = _STRAY_DOC_TAG_RE.sub("", out)

    out = _TEMPLATE_LABEL_RE.sub("", out)
    out = _FENCED_HTML_RE.sub("", out)
    out = _leaked_cta_to_markdown(out, cta_href)
    out = _tables_to_markdown(out)
    out = _SCRIPT_RE.sub("", out)
    # Any CSS still lying around is never part of an article body.
    out = _STYLE_RE.sub("", out)

    return _BLANKS_RE.sub("\n\n", out).strip() + ("\n" if article.endswith("\n") else "")


def strip_html_for_word_count(text: str) -> str:
    """Remove CSS/script/tags so HTML shells do not count as article words."""
    if not text or "<" not in text:
        return text
    out = _DOCTYPE_RE.sub(" ", text)
    out = _STYLE_RE.sub(" ", out)
    out = _SCRIPT_RE.sub(" ", out)
    return _TAG_RE.sub(" ", out)
