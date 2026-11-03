"""Workspace HTML CTA templates: fill headline/body/button per article.

Each client stores an HTML shell (and usually CSS) in ``cta_guidelines.md``.
Final output still writes markdown CTAs (bold + description + link); this module
swaps those blocks for rendered HTML, keeping the workspace contact URL fixed.
"""

from __future__ import annotations

import html
import re
from typing import NamedTuple

# Placeholders editors may put in the workspace template.
_HEADLINE_KEYS = ("headline", "heading", "title", "h3")
_BODY_KEYS = ("body", "description", "text", "copy", "p")
_BUTTON_KEYS = ("button", "button_label", "cta_label", "label", "link_text")
_HREF_KEYS = ("href", "url", "link", "cta_href", "cta_url")

_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}",
    re.IGNORECASE,
)

# Standalone bold heading line: **Heading text**
_MD_BOLD_LINE_RE = re.compile(
    r"(?m)^[ \t]*\*\*(?P<head>[^*][^\n*]*)\*\*[ \t]*$"
)
_MD_LINK_LINE_RE = re.compile(
    r"(?m)^[ \t]*\[(?P<label>[^\]]{1,120})\]\((?P<href>[^)\s]+)\)[ \t]*$"
)

_H3_RE = re.compile(r"(<h3\b[^>]*>)(.*?)(</h3>)", re.IGNORECASE | re.DOTALL)
_P_RE = re.compile(r"(<p\b[^>]*>)(.*?)(</p>)", re.IGNORECASE | re.DOTALL)
_A_HREF_RE = re.compile(
    r'(<a\b[^>]*\bhref\s*=\s*)(["\'])([^"\']*)\2',
    re.IGNORECASE,
)
_A_OPEN_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_A_CLOSE = "</a>"
_STYLE_BLOCK_RE = re.compile(
    r"<style\b[^>]*>[\s\S]*?</style>",
    re.IGNORECASE,
)


class MarkdownCta(NamedTuple):
    start: int
    end: int
    headline: str
    body: str
    button: str
    href: str


def extract_cta_html_template(cta_text: str) -> str | None:
    """Pull the HTML CTA shell from ``cta_guidelines.md`` when present."""
    text = cta_text or ""
    if not text.strip():
        return None

    # Prefer an explicit section heading.
    section = re.search(
        r"(?is)(?:^|\n)#{2,3}\s*HTML\s+CTA\s+Template\s*\n+"
        r"(?P<body>[\s\S]+?)(?=\n#{2,3}\s|\Z)",
        text,
    )
    chunk = section.group("body").strip() if section else text

    # Any fenced block (``` html, ```HTML, ```css, bare ```) that looks like the shell.
    for fenced in re.finditer(
        r"(?is)```[ \t]*[a-z]*[ \t]*\n(?P<html>[\s\S]*?)```",
        chunk,
    ):
        html_block = _clean_template(fenced.group("html"))
        if _looks_like_cta_html(html_block):
            return html_block

    # Bare HTML in the section (or whole file) without fences.
    bare = _clean_template(chunk)
    if _looks_like_cta_html(bare):
        return bare

    # Last resort: first <div …>…</div> plus optional trailing <style>.
    div = re.search(
        r"(?is)(<div\b[^>]*>[\s\S]*?</div>)(\s*<style\b[^>]*>[\s\S]*?</style>)?",
        text,
    )
    if div and _looks_like_cta_html(div.group(0)):
        return _clean_template(div.group(0))

    return None


_FENCE_LINE_RE = re.compile(r"(?m)^[ \t]*`{3,}[ \t]*[A-Za-z]*[ \t]*$\n?")


def _clean_template(block: str) -> str:
    """Keep only the HTML of a template: no code fences, no prose around it.

    Fence lines or prose inside the template would be copied into every CTA in
    the article, and a stray ``` makes the preview show the rest of the article
    as a code block.
    """
    out = _FENCE_LINE_RE.sub("", block or "")
    first = re.search(r"<(?:div|section|style|aside|p|h[1-6]|a)\b", out, re.I)
    if first:
        out = out[first.start():]
    last = max(
        (m.end() for m in re.finditer(r"</(?:div|section|style|aside)\s*>", out, re.I)),
        default=0,
    )
    if last:
        out = out[:last]
    return out.strip()


def _looks_like_cta_html(block: str) -> bool:
    low = (block or "").lower()
    if "<" not in low:
        return False
    has_slot = bool(_PLACEHOLDER_RE.search(block))
    has_structure = ("<h3" in low or "<p" in low) and ("<a" in low or "href" in low)
    return has_slot or has_structure


def resolve_cta_html_template(client_id: str) -> str | None:
    """Load HTML CTA template for a workspace, or None if not configured."""
    from . import artifacts

    try:
        text = artifacts.read_context_file(client_id, "cta_guidelines.md")
    except ValueError:
        text = None
    if not text:
        # Fallback: direct disk read (same path layout as context files).
        from . import config

        path = config.CLIENTS_DIR / client_id / "context" / "cta_guidelines.md"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = None
    return extract_cta_html_template(text or "")


def _norm_href(href: str) -> str:
    return (href or "").strip().rstrip("/")


_CTA_PATH_TOKENS = (
    "/contact",
    "book-a-demo",
    "get-in-touch",
    "rendez-vous",
    "book-a-call",
)


def _path_of(href: str) -> str:
    h = _norm_href(href)
    if "://" in h:
        rest = h.split("://", 1)[1]
        return "/" + rest.split("/", 1)[-1] if "/" in rest else "/"
    return h if h.startswith("/") else f"/{h}"


def _looks_like_cta_href(href: str) -> bool:
    low = (href or "").lower()
    return any(tok in low for tok in _CTA_PATH_TOKENS) or "demo" in low


def _hrefs_match(a: str, b: str) -> bool:
    na, nb = _norm_href(a), _norm_href(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    pa, pb = _path_of(na), _path_of(nb)
    if pa == pb:
        return True
    if na.endswith(nb) or nb.endswith(na):
        return True
    # Both look like CTA destinations (contact/demo) — treat as match.
    return _looks_like_cta_href(na) and _looks_like_cta_href(nb)


def _same_site_cta(href: str, preferred: str) -> bool:
    """True when href and preferred share a host and look like contact CTAs."""
    a, b = _norm_href(href), _norm_href(preferred)
    if not a or not b:
        return False
    if "://" not in a and "://" not in b:
        return False

    def _host(url: str) -> str:
        if "://" not in url:
            return ""
        return url.split("://", 1)[1].split("/", 1)[0].lower()

    ha, hb = _host(a), _host(b)
    if ha and hb and ha == hb:
        return True
    # Absolute article link vs relative preferred (or vice versa).
    if ha and not hb and _looks_like_cta_href(a):
        return True
    if hb and not ha and _looks_like_cta_href(a):
        return _path_of(a) == _path_of(b) or _looks_like_cta_href(b)
    return False


def find_markdown_ctas(article: str, *, cta_href: str | None = None) -> list[MarkdownCta]:
    """Locate markdown CTA triples (bold + body + link) in article markdown."""
    text = article or ""
    preferred = _norm_href(cta_href or "")
    lines = text.splitlines(keepends=True)
    # Absolute offsets for each line start.
    starts: list[int] = []
    pos = 0
    for line in lines:
        starts.append(pos)
        pos += len(line)

    found: list[MarkdownCta] = []
    i = 0
    while i < len(lines):
        bold = _MD_BOLD_LINE_RE.match(lines[i])
        if not bold:
            i += 1
            continue

        # Collect following non-empty body lines until a CTA link line.
        body_parts: list[str] = []
        j = i + 1
        # Allow blank lines between heading and body / body and link.
        while j < len(lines) and not lines[j].strip():
            j += 1
        while j < len(lines):
            raw = lines[j]
            stripped = raw.strip()
            if not stripped:
                # Blank line inside body — stop if next non-blank is a link.
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines) and _MD_LINK_LINE_RE.match(lines[k]):
                    j = k
                    break
                j += 1
                continue
            if stripped.startswith("#") or stripped.startswith("!["):
                break
            if _MD_LINK_LINE_RE.match(raw):
                break
            # Another standalone bold heading → not part of this CTA body.
            if _MD_BOLD_LINE_RE.match(raw):
                break
            body_parts.append(stripped)
            j += 1
            if len(body_parts) >= 4:
                break

        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            i += 1
            continue
        link = _MD_LINK_LINE_RE.match(lines[j])
        if not link or not body_parts:
            i += 1
            continue

        href = (link.group("href") or "").strip()
        # Prefer matching the workspace CTA URL; also accept common CTA paths.
        # When a preferred href is set, still accept same-site absolute links
        # (e.g. https://arsuno.ai/contact vs /contact).
        if preferred:
            if not (
                _hrefs_match(href, preferred)
                or _looks_like_cta_href(href)
                or _same_site_cta(href, preferred)
            ):
                i += 1
                continue
        elif not _looks_like_cta_href(href):
            i += 1
            continue

        body = re.sub(r"\s+", " ", " ".join(body_parts)).strip()
        # Body may include markdown emphasis; strip for length check only.
        body_plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        if not body_plain or len(body_plain) > 500:
            i += 1
            continue

        start = starts[i]
        end = starts[j] + len(lines[j])
        found.append(
            MarkdownCta(
                start=start,
                end=end,
                headline=(bold.group("head") or "").strip(),
                body=body,
                button=(link.group("label") or "").strip(),
                href=href,
            )
        )
        i = j + 1
    return found


def render_cta_html(
    template: str,
    *,
    headline: str,
    body: str,
    button: str,
    href: str,
    include_style: bool = True,
) -> str:
    """Fill a workspace HTML template with per-article copy."""
    tpl = (template or "").strip()
    if not tpl:
        return ""

    safe_headline = html.escape((headline or "").strip())
    # Allow a single <strong>…</strong> for brand emphasis if the model used **x**.
    safe_body = _escape_body_allow_strong(body or "")
    safe_button = html.escape((button or "").strip())
    safe_href = html.escape((href or "").strip(), quote=True)

    values = {
        **{k: safe_headline for k in _HEADLINE_KEYS},
        **{k: safe_body for k in _BODY_KEYS},
        **{k: safe_button for k in _BUTTON_KEYS},
        **{k: safe_href for k in _HREF_KEYS},
    }

    if _PLACEHOLDER_RE.search(tpl):

        def _sub(m: re.Match[str]) -> str:
            key = (m.group(1) or "").strip().lower()
            return values.get(key, m.group(0))

        out = _PLACEHOLDER_RE.sub(_sub, tpl)
    else:
        out = _fill_structural_template(
            tpl,
            headline=safe_headline,
            body=safe_body,
            button=safe_button,
            href=safe_href,
        )

    if not include_style:
        out = _STYLE_BLOCK_RE.sub("", out).strip()

    return out.strip()


def _escape_body_allow_strong(text: str) -> str:
    """Escape body; convert markdown **brand** to <strong>brand</strong>."""
    raw = (text or "").strip()
    if not raw:
        return ""
    parts: list[str] = []
    last = 0
    for m in re.finditer(r"\*\*([^*]+)\*\*", raw):
        parts.append(html.escape(raw[last : m.start()]))
        parts.append(f"<strong>{html.escape(m.group(1))}</strong>")
        last = m.end()
    parts.append(html.escape(raw[last:]))
    return "".join(parts)


def _fill_structural_template(
    template: str,
    *,
    headline: str,
    body: str,
    button: str,
    href: str,
) -> str:
    """Replace first h3, first p, and primary CTA <a> when no {{placeholders}}."""
    out = template

    def _h3(m: re.Match[str]) -> str:
        return f"{m.group(1)}{headline}{m.group(3)}"

    out, n_h3 = _H3_RE.subn(_h3, out, count=1)

    def _p(m: re.Match[str]) -> str:
        return f"{m.group(1)}{body}{m.group(3)}"

    out, n_p = _P_RE.subn(_p, out, count=1)

    out, n_href = _A_HREF_RE.subn(
        lambda m: f"{m.group(1)}{m.group(2)}{href}{m.group(2)}",
        out,
        count=1,
    )

    # Replace visible label inside the first <a>…</a>, keep nested spans (icon).
    a_open = _A_OPEN_RE.search(out)
    if a_open:
        start = a_open.end()
        close = out.lower().find(_A_CLOSE, start)
        if close != -1:
            inner = out[start:close]
            # Keep trailing icon/markup spans; replace leading text node.
            span_m = re.search(r"(?i)(\s*<span\b)", inner)
            if span_m:
                new_inner = f"{button}{inner[span_m.start():]}"
            else:
                new_inner = button
            out = out[:start] + new_inner + out[close:]

    # If structure was missing, fall back to a minimal block.
    if n_h3 == 0 and n_p == 0 and n_href == 0 and "<" not in out:
        return (
            f'<div class="workspace-cta">\n'
            f"  <h3>{headline}</h3>\n"
            f"  <p>{body}</p>\n"
            f'  <a href="{href}">{button}</a>\n'
            f"</div>"
        )
    return out


def inject_cta_html(
    article: str,
    template: str,
    *,
    cta_href: str,
) -> str:
    """Replace markdown CTA blocks with workspace HTML (style once, then repeats)."""
    if not (article or "").strip() or not (template or "").strip():
        return article

    blocks = find_markdown_ctas(article, cta_href=cta_href)
    if not blocks:
        return article

    href = (cta_href or "").strip() or "/contact"
    parts: list[str] = []
    cursor = 0
    style_done = False
    for cta in blocks:
        rendered = compact_html_block(
            render_cta_html(
                template,
                headline=cta.headline,
                body=cta.body,
                button=cta.button,
                href=href,
                include_style=not style_done,
            )
        )
        if not html_is_balanced(rendered):
            # A broken shell would swallow the rest of the article: keep the markdown CTA.
            continue
        style_done = style_done or "<style" in rendered.lower()
        parts.append(article[cursor : cta.start].rstrip() + "\n\n")
        # One solid block between blank lines: markdown renderers and the preview
        # then treat it as raw HTML and go back to normal markdown right after it.
        parts.append(rendered + "\n\n")
        cursor = cta.end
        while cursor < len(article) and article[cursor] in "\r\n":
            cursor += 1
    parts.append(article[cursor:])
    return "".join(parts)


_BLOCK_TAGS = ("div", "section", "style", "aside", "a")


def compact_html_block(html_text: str) -> str:
    """One contiguous HTML block: no blank lines, no indentation, no code fences.

    A blank line inside a pasted template ends the HTML block for markdown
    renderers, and an indented line after it becomes a code block, so the rest of
    the article shows up as raw text.
    """
    lines = []
    for raw in (html_text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or re.fullmatch(r"`{3,}[A-Za-z]*", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def html_is_balanced(html_text: str) -> bool:
    """True when every block-level tag we emit is closed (and none is closed twice)."""
    for tag in _BLOCK_TAGS:
        opens = len(re.findall(rf"<{tag}\b(?![^>]*/>)", html_text or "", re.I))
        closes = len(re.findall(rf"</{tag}\s*>", html_text or "", re.I))
        if opens != closes:
            return False
    return True


def apply_workspace_cta_html(
    article: str,
    *,
    client_id: str,
    cta_href: str | None = None,
) -> str:
    """If the workspace has an HTML CTA template, wrap markdown CTAs with it."""
    template = resolve_cta_html_template(client_id)
    if not template:
        return article

    from .context_extractor import resolve_cta_href

    href = (cta_href or "").strip() or resolve_cta_href(client_id)
    out = inject_cta_html(article, template, cta_href=href)
    # A stray ``` around the shell would make the preview show the rest of the
    # article as a code block (raw markdown).
    from .html_leak import unwrap_html_fences

    return unwrap_html_fences(out)
