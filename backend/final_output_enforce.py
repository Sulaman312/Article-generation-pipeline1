"""Repair final_output artifacts: FAQ section, external links, word count, JSON-LD."""

from __future__ import annotations

import logging
import re

from . import artifacts
from . import config
from . import french_language
from . import editorial_input
from . import faq_schema
from . import writing_format_enforce
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")
_SKIP_URL_SUBSTR = ("youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com/")

def extract_citable_urls(*texts: str, exclude_host_substrings: tuple[str, ...] = ()) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in texts:
        for m in _URL_RE.finditer(raw or ""):
            url = m.group(0).rstrip(".,;:")
            low = url.lower()
            if any(s in low for s in _SKIP_URL_SUBSTR):
                continue
            if any(s in low for s in exclude_host_substrings):
                continue
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out


_INTERNAL_STANDALONE_RE = re.compile(
    r"^\[INTERNAL LINK:\s*(.+?)\s*→\s*(.+?)\]\s*$",
    re.I | re.M,
)
_INTERNAL_INLINE_RE = re.compile(r"\]\(INTERNAL:\s*[^)]+\)", re.I)


def count_internal_link_placeholders(markdown: str) -> int:
    if not markdown:
        return 0
    n_standalone = len(re.findall(r"\[INTERNAL LINK:", markdown, re.I))
    n_inline = len(_INTERNAL_INLINE_RE.findall(markdown))
    return n_standalone + n_inline


def _short_anchor(text: str, max_words: int = 3) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", text or "")
    if not words:
        return "learn more"
    return " ".join(words[:max_words])


def _pick_phrase_for_link(sentence: str, max_words: int = 3) -> str | None:
    """Pick a 2–3 word phrase in a sentence that is not already inside a link."""
    if re.search(r"\[[^\]]+\]\(", sentence):
        return None
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", sentence)
    if len(words) < 5:
        return None
    start = max(1, len(words) // 2 - 1)
    chunk = words[start : start + max_words]
    if len(chunk) < 2:
        chunk = words[-3:] if len(words) >= 3 else words
    return " ".join(chunk[:max_words])


def _wrap_first_phrase(sentence: str, phrase: str, link_inner: str) -> str:
    """Replace the first occurrence of phrase with [phrase](link_inner)."""
    if not phrase or phrase not in sentence:
        return sentence
    pattern = re.compile(re.escape(phrase), re.I)
    return pattern.sub(f"[{phrase}]({link_inner})", sentence, count=1)


def _last_nonempty_line_index(lines: list[str]) -> int:
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            return i
    return -1


def inline_standalone_internal_links(article: str) -> str:
    """Move standalone [INTERNAL LINK: …] lines into the previous paragraph."""
    lines = article.split("\n")
    out: list[str] = []
    for line in lines:
        m = _INTERNAL_STANDALONE_RE.match(line.strip())
        if m and out:
            anchor = _short_anchor(m.group(1).strip())
            cluster = m.group(2).strip()
            link = f"[{anchor}](INTERNAL: {cluster})"
            idx = _last_nonempty_line_index(out)
            if idx < 0:
                out.append(link)
                continue
            prev = out[idx].rstrip()
            if prev and not prev.endswith((".", "?", "!")):
                prev += "."
            out[idx] = f"{prev} {link}" if prev else link
            continue
        out.append(line)
    return _merge_orphan_link_lines(out)


_ORPHAN_LINK_LINE_RE = re.compile(
    r"^\[([^\]]{1,60})\]\((INTERNAL:[^)]+|https?://[^)]+)\)\s*$",
    re.I,
)


def _merge_orphan_link_lines(lines: list[str]) -> str:
    """Attach a paragraph that is only a markdown link to the prior paragraph."""
    out: list[str] = []
    for line in lines:
        m = _ORPHAN_LINK_LINE_RE.match(line.strip())
        if m and out:
            idx = _last_nonempty_line_index(out)
            if idx >= 0:
                prev = out[idx].rstrip()
                if prev and not prev.endswith((".", "?", "!")):
                    prev += "."
                out[idx] = f"{prev} {line.strip()}" if prev else line.strip()
                continue
        out.append(line)
    return "\n".join(out)


def move_trailing_external_links_inline(article: str) -> str:
    """Turn end-of-sentence (Host) links into mid-sentence 2–3 word anchors."""
    trailing = re.compile(
        r"(?<=[.!?])\s*\(\[([^\]]+)\]\((https?://[^)]+)\)\)",
        re.I,
    )

    def _fix_para(para: str) -> str:
        while True:
            m = trailing.search(para)
            if not m:
                break
            url = m.group(2)
            para = para[: m.start()] + para[m.end() :]
            sentences = re.split(r"(?<=[.!?])\s+", para.strip())
            if not sentences:
                break
            placed = False
            for idx in range(len(sentences) - 1, -1, -1):
                sent = sentences[idx].strip()
                if not sent or re.search(r"\]\(https?://", sent, re.I):
                    continue
                phrase = _pick_phrase_for_link(sent)
                if not phrase:
                    continue
                sentences[idx] = _wrap_first_phrase(sent, phrase, url)
                placed = True
                break
            if not placed and sentences:
                phrase = _pick_phrase_for_link(sentences[0]) or "research shows"
                sentences[0] = _wrap_first_phrase(sentences[0], phrase, url)
            para = " ".join(sentences)
        return para

    parts = article.split("\n\n")
    return "\n\n".join(_fix_para(p) if p.strip() else p for p in parts)


def _cluster_match_paragraph(para: str, cluster: str) -> bool:
    tokens = re.findall(r"[a-z]{4,}", (cluster or "").lower())
    text = para.lower()
    hits = sum(1 for t in tokens if t in text)
    return hits >= 2 or any(t in text for t in tokens[:3] if len(t) > 6)


def inject_internal_links_programmatic(
    article: str, clusters: list[str], max_links: int = 4
) -> str:
    """Weave internal placeholders inline with short anchors when the model skipped them."""
    if not clusters or count_internal_link_placeholders(article) >= 2:
        return article

    paragraphs = article.split("\n\n")
    used_clusters: set[str] = set()
    link_n = 0
    out: list[str] = []
    for para in paragraphs:
        if link_n >= max_links:
            out.append(para)
            continue
        stripped = para.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or "[INTERNAL LINK:" in stripped
            or _INTERNAL_INLINE_RE.search(stripped)
            or len(stripped) < 80
        ):
            out.append(para)
            continue
        chosen = None
        for cluster in clusters:
            if cluster in used_clusters:
                continue
            if _cluster_match_paragraph(stripped, cluster):
                chosen = cluster
                break
        if not chosen:
            out.append(para)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        target_i = next(
            (
                i
                for i, s in enumerate(sentences)
                if s.strip() and not re.search(r"\]\(INTERNAL:", s, re.I)
            ),
            0,
        )
        phrase = _pick_phrase_for_link(sentences[target_i]) or _short_anchor(chosen)
        sentences[target_i] = _wrap_first_phrase(
            sentences[target_i],
            phrase,
            f"INTERNAL: {chosen}",
        )
        out.append(" ".join(sentences))
        used_clusters.add(chosen)
        link_n += 1
    return "\n\n".join(out)


def inject_form_internal_links(
    article: str, links: list[dict[str, str]] | None, max_links: int = 6
) -> str:
    """Weave missing article-form Internal Links into body prose mid-sentence."""
    missing = editorial_input.missing_form_internal_links(article, links)
    if not missing:
        return article

    paragraphs = article.split("\n\n")
    used = 0
    link_i = 0
    out: list[str] = []
    skip_next_body = False
    for para in paragraphs:
        if used >= max_links or link_i >= len(missing):
            out.append(para)
            continue
        stripped = para.strip()
        heading_m = re.match(
            r"^##\s+(key\s+takeaways?|frequently asked|questions)",
            stripped,
            re.I,
        )
        if heading_m:
            skip_next_body = True
            out.append(para)
            continue
        if (
            not stripped
            or stripped.startswith("#")
            or "[INTERNAL LINK:" in stripped
            or len(stripped) < 70
            or skip_next_body
        ):
            if stripped:
                skip_next_body = False
            out.append(para)
            continue

        item = missing[link_i]
        href = editorial_input.form_internal_link_href(item)
        if not href or editorial_input.article_has_form_internal_href(stripped, href):
            out.append(para)
            continue

        title_words = re.findall(r"[A-Za-z0-9]{3,}", item.get("title") or "")
        hay = stripped.lower()
        title_hit = sum(1 for w in title_words if w.lower() in hay) >= max(1, min(2, len(title_words)))
        if not title_hit and used == 0 and link_i == 0:
            # First missing link can go in the first suitable body paragraph.
            title_hit = True
        elif not title_hit and used > 0:
            # Prefer a later paragraph that mentions the page title.
            remaining = "\n\n".join(paragraphs[len(out) + 1 :])
            if any(w.lower() in remaining.lower() for w in title_words[:3]):
                out.append(para)
                continue

        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        target_i = next(
            (
                i
                for i, s in enumerate(sentences)
                if s.strip() and not re.search(r"\]\([^)]+\)", s)
            ),
            0,
        )
        phrase = None
        sent = sentences[target_i]
        for n in (3, 2):
            chunk = " ".join(title_words[:n])
            if chunk and re.search(re.escape(chunk), sent, re.I):
                phrase = re.search(re.escape(chunk), sent, re.I).group(0)
                break
        if not phrase:
            phrase = _pick_phrase_for_link(sent) or _short_anchor(
                item.get("title") or href
            )
        if phrase and phrase.lower() in sent.lower():
            sentences[target_i] = _wrap_first_phrase(sent, phrase, href)
        else:
            anchor = _short_anchor(item.get("title") or href)
            sentences[target_i] = f"{sent.rstrip()} [{anchor}]({href})"
        out.append(" ".join(sentences))
        used += 1
        link_i += 1
    return "\n\n".join(out)


def count_external_markdown_links(markdown: str) -> int:
    if not markdown:
        return 0
    n = 0
    for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", markdown, re.I):
        if "internal link:" in m.group(1).lower():
            continue
        n += 1
    return n


def _needs_faq(article_md: str, manual: dict | None) -> bool:
    if not editorial_input.should_include_faq(manual):
        return False
    return len(faq_schema.extract_faq_pairs(article_md)) < 2


def _needs_external(article_md: str, manual: dict | None) -> bool:
    if not editorial_input.should_include_external_links(manual):
        return False
    return count_external_markdown_links(article_md) < 3


def inject_external_links_programmatic(article: str, urls: list[str], max_links: int = 5) -> str:
    """Weave outbound [2–3 word](https://…) links into prose — never append at paragraph end."""
    if not urls or count_external_markdown_links(article) >= 3:
        return article

    paragraphs = article.split("\n\n")
    url_i = 0
    out: list[str] = []
    for para in paragraphs:
        if url_i >= max_links:
            out.append(para)
            continue
        stripped = para.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or "[INTERNAL LINK:" in stripped
            or _INTERNAL_INLINE_RE.search(stripped)
            or count_external_markdown_links(stripped) >= 1
        ):
            out.append(para)
            continue
        if len(stripped) < 60:
            out.append(para)
            continue
        url = urls[url_i % len(urls)]
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        placed = False
        for idx, sent in enumerate(sentences):
            if re.search(r"\]\(https?://", sent, re.I):
                continue
            phrase = _pick_phrase_for_link(sent)
            if not phrase:
                continue
            sentences[idx] = _wrap_first_phrase(sent, phrase, url)
            placed = True
            break
        if not placed and sentences:
            phrase = _pick_phrase_for_link(sentences[0]) or "industry research"
            sentences[0] = _wrap_first_phrase(sentences[0], phrase, url)
        out.append(" ".join(sentences))
        url_i += 1
    return "\n\n".join(out)


def normalize_article_links(article: str, clusters: list[str] | None = None) -> str:
    """Inline standalone internal links and trailing external citations."""
    text = inline_standalone_internal_links(article)
    text = move_trailing_external_links_inline(text)
    if clusters:
        text = inject_internal_links_programmatic(text, clusters)
    return text


_CTA_COPY: dict[str, tuple[str, str, str]] = {
    "en": (
        "Want help putting this into practice?",
        "Talk with our team about your situation and leave with a clear next step.",
        "Talk to our team",
    ),
    "fr": (
        "Besoin d'aide pour passer à l'action ?",
        "Parlez de votre situation avec notre équipe et repartez avec une prochaine étape claire.",
        "Parler à l'équipe",
    ),
}
_CTA_SKIP_HEADING = re.compile(
    r"^##\s+(key\s+takeaways?|à\s+retenir|frequently asked|questions\s+fr[ée]quentes|"
    r"conclusion|summary|r[ée]sum[ée])",
    re.I,
)


def count_cta_blocks(article: str, cta_href: str | None) -> int:
    """Markdown CTA triples plus HTML CTA anchors that point at the CTA URL."""
    from . import cta_html

    n = len(cta_html.find_markdown_ctas(article, cta_href=cta_href))
    target = (cta_href or "").strip().rstrip("/")
    if target:
        n += len(
            re.findall(
                r'<a\b[^>]*\bhref\s*=\s*["\']' + re.escape(target) + r"/?[\"']",
                article,
                re.I,
            )
        )
    return n


MAX_CTAS = 2
_TAKEAWAY_HEADING = re.compile(
    r"^##\s+(key\s+takeaways?|à\s+retenir|points?\s+cl[ée]s?)", re.I
)
_FAQ_HEADING = re.compile(r"^##\s+(frequently asked|questions\s+fr[ée]quentes)", re.I)


def _line_offsets(lines: list[str]) -> list[int]:
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    return offsets


def _drop_spans(article: str, spans: list[tuple[int, int]]) -> str:
    for start, end in sorted(spans, reverse=True):
        article = article[:start].rstrip("\n") + "\n\n" + article[end:].lstrip("\n")
    return article


def _first_content_h2_offset(article: str) -> int | None:
    """Char offset of the first H2 that is not the opening takeaways block."""
    for m in re.finditer(r"(?m)^##\s+\S.*$", article):
        if not _TAKEAWAY_HEADING.match(m.group(0).strip()):
            return m.start()
    return None


def ensure_min_ctas(
    article: str,
    *,
    cta_href: str | None,
    lang: str = "en",
    cta_examples: list[str] | None = None,
    min_ctas: int = MAX_CTAS,
    max_ctas: int = MAX_CTAS,
) -> tuple[str, int]:
    """Exactly ``max_ctas`` CTAs, in the middle and at the end, never in the opening.

    - CTAs sitting before the first content section (opening block) are removed.
    - Extra CTAs beyond ``max_ctas`` are removed (the last one and the one nearest
      the middle are kept).
    - Missing CTAs are added: one between sections, one at the end (before the FAQ).

    Returns ``(article, number_inserted)``.
    """
    from . import cta_html

    if not (article or "").strip():
        return article, 0
    href = (cta_href or "").strip() or "/contact"
    text = article

    # 1. Opening block: no CTA before the first content section.
    first_content = _first_content_h2_offset(text)
    if first_content is not None:
        early = [
            (c.start, c.end)
            for c in cta_html.find_markdown_ctas(text, cta_href=href)
            if c.start < first_content
        ]
        if early:
            logger.info("removed %s CTA block(s) from the opening of the article", len(early))
            text = _drop_spans(text, early)

    # 2. Never more than max_ctas.
    found = cta_html.find_markdown_ctas(text, cta_href=href)
    if len(found) > max_ctas:
        mid = len(text) / 2
        keep = {len(found) - 1}
        others = sorted(range(len(found) - 1), key=lambda k: abs(found[k].start - mid))
        keep.update(others[: max(0, max_ctas - 1)])
        extra = [(c.start, c.end) for k, c in enumerate(found) if k not in keep]
        logger.info("removed %s extra CTA block(s) (max %s)", len(extra), max_ctas)
        text = _drop_spans(text, extra)

    # 3. Top up to min_ctas.
    have = count_cta_blocks(text, href)
    need = min(min_ctas, max_ctas) - have
    if need <= 0:
        return text, 0

    lines = text.split("\n")
    offsets = _line_offsets(lines)
    h2_idx = [i for i, ln in enumerate(lines) if re.match(r"^##\s+\S", ln)]
    content_h2 = [i for i in h2_idx if not _TAKEAWAY_HEADING.match(lines[i].strip())]
    existing = cta_html.find_markdown_ctas(text, cta_href=href)

    def occupied(slot: int) -> bool:
        """A CTA already sits in the section right before this slot."""
        prev = max((h for h in h2_idx if h < slot), default=-1)
        lo = offsets[prev] if prev >= 0 else 0
        hi = offsets[slot] if slot < len(offsets) else len(text)
        return any(lo <= c.start < hi for c in existing)

    # "In between": before a content H2 from the second one on, not FAQ / conclusion.
    middle = [
        i
        for i in content_h2[1:]
        if not _CTA_SKIP_HEADING.match(lines[i].strip()) and not occupied(i)
    ]
    # "At the end": just before the FAQ, else the very end of the article.
    faq = next((i for i in h2_idx if _FAQ_HEADING.match(lines[i].strip())), None)
    end_slot = faq if faq is not None else len(lines)
    end_free = not occupied(end_slot)

    total = len(text) or 1
    late = any(c.start / total > 0.65 for c in existing)
    wants: list[str] = []
    if need >= 2:
        wants = ["middle", "end"]
    elif late:
        wants = ["middle"]
    else:
        wants = ["end"]

    chosen: list[int] = []
    for want in wants:
        if want == "middle" and middle:
            target = total * 0.5
            slot = min(middle, key=lambda i: abs(offsets[i] - target))
            middle.remove(slot)
            chosen.append(slot)
        elif want == "end" and end_free and end_slot not in chosen:
            chosen.append(end_slot)
        elif middle:
            slot = min(middle, key=lambda i: abs(offsets[i] - total * 0.8))
            middle.remove(slot)
            chosen.append(slot)
        elif end_slot not in chosen:
            chosen.append(end_slot)
    if len(chosen) < need and len(lines) not in chosen:
        chosen.append(len(lines))  # short article: last spot is the very end
    if not chosen:
        return text, 0

    headline, body, button = _CTA_COPY.get((lang or "en").lower(), _CTA_COPY["en"])
    for ex in cta_examples or []:
        ex = (ex or "").strip()
        if 1 <= len(ex.split()) <= 6 and "\u2014" not in ex and "\u2013" not in ex:
            button = ex.rstrip(".")
            break

    block = f"**{headline}**\n\n{body}\n\n[{button}]({href})\n"
    for slot in sorted(chosen, reverse=True):
        if slot >= len(lines):
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend([""] + block.split("\n"))
        else:
            lines[slot:slot] = block.split("\n") + [""]
    logger.info("inserted %s fallback CTA block(s) (model wrote %s)", len(chosen), have)
    return "\n".join(lines), len(chosen)


def inject_faq_template(
    article: str,
    topic: str = "",
    *,
    manual: dict | None = None,
    paa_faq_research: str = "",
) -> str:
    """Insert a minimal FAQ block before Conclusion when the model skipped it."""
    if len(faq_schema.extract_faq_pairs(article)) >= 2:
        return article

    lang = editorial_input.article_language_from_manual(manual)
    heading = editorial_input.faq_heading_for_language(lang)
    from . import paa_faq

    bank_prompt = paa_faq.format_faq_bank_for_prompt(paa_faq_research)
    # No stock Q&A is ever inserted: the model writes the FAQ, and we retry until the
    # result has real questions with answers (or fail the step).
    attempts = config.QUALITY_RETRY_ATTEMPTS
    for attempt in range(attempts):
        result = _inject_faq_llm(
            article,
            topic=topic,
            lang=lang,
            heading=heading,
            faq_bank_prompt=bank_prompt,
        )
        if len(faq_schema.extract_faq_pairs(result)) >= 2:
            return result
        logger.warning(
            "FAQ injection returned fewer than 2 Q&As (attempt %s/%s)", attempt + 1, attempts
        )
    raise RuntimeError(
        f"Final output: the model did not produce a usable FAQ after {attempts} attempts."
    )


def _inject_faq_llm(
    article: str,
    *,
    topic: str,
    lang: str,
    heading: str,
    faq_bank_prompt: str = "",
) -> str:
    """Generate a topic-relevant FAQ block in the article language."""
    language_label = editorial_input.language_label_for_code(lang)
    french = (lang or "").lower() == "fr"
    system = (
        f"Return ONLY the full article markdown. Write exactly ONE FAQ section in "
        f"{language_label} using H2 `{heading}`. Prefer the provided FAQ bank questions. "
        "Do not add FAQ blocks in any other language. Do not invent brands, products, or prices. "
        "Each FAQ answer must be one normal paragraph of 2-4 sentences (max ~70 words). "
        "Do not use bullets, numbered lists, or one sentence per line. "
        "Do not pad FAQ to hit article word count."
    )
    if french:
        system += (
            f"\n{french_language.FRENCH_RULE}\nUse a French term, never an English one "
            "(bol, collation, formule, accompagnement...). Each answer must really answer "
            "its question."
        )
    bank = faq_bank_prompt.strip() or (
        "No FAQ bank provided — write only as many specific questions as the topic supports "
        "(prefer 4–7; fewer if thin)."
    )
    user = (
        f"Topic: {topic or 'article'}\n\n"
        f"{bank}\n\n"
        f"Add the FAQ section before the closing H2/CTA when possible.\n\n"
        f"---ARTICLE---\n{article.strip()}\n"
    )
    return claude.chat_complete(
        system,
        user,
        step_label=f"Final output FAQ inject ({language_label})",
        max_tokens=8192,
        temperature=0.35,
    ).strip()


def _trim_article_llm(article_md: str, target: int, topic: str) -> str:
    """Section-preserving backup trim (prefer draft-time length control)."""
    from . import word_count_enforce

    low, high = editorial_input.word_count_bounds(target)
    current = editorial_input.count_article_words(article_md)
    if current <= high:
        return article_md
    logger.info(
        "final_output section trim: %s words -> target %s (%s–%s) topic=%r",
        current,
        target,
        low,
        high,
        (topic or "")[:80],
    )
    return word_count_enforce.trim_article_by_sections(
        article_md,
        target,
        step_label="Final output section trim",
        max_passes=3,
    )


def _repair_article_with_llm(
    article_md: str,
    *,
    add_faq: bool,
    add_external: bool,
    urls: list[str],
    topic: str,
    word_target: int | None,
    manual: dict | None = None,
) -> str:
    current = editorial_input.count_article_words(article_md)
    tasks: list[str] = []
    lang = editorial_input.article_language_from_manual(manual)
    faq_heading = editorial_input.faq_heading_for_language(lang)
    language_label = editorial_input.language_label_for_code(lang)
    if word_target:
        low, high = editorial_input.word_count_bounds(word_target)
        tasks.append(
            f"Body prose (FAQ excluded) MUST be {low:,}–{high:,} words (form target "
            f"{word_target:,}). Current body: {current:,}. Trim filler before adding FAQ/links."
        )
    if add_faq:
        tasks.append(
            f"Add ONE FAQ section with H2 `{faq_heading}` and 5–7 H3 Q&As in "
            f"{language_label} before the conclusion. Do not add FAQ in another language."
        )
    if add_external:
        url_block = "\n".join(f"- {u}" for u in urls[:10]) or "- (none)"
        tasks.append(
            f"Add 3–5 outbound `[anchor](url)` links using ONLY:\n{url_block}"
        )
    system = (
        "Return ONLY the full article markdown. Keep H1, H2 structure, tone, and "
        "inline internal/external links with 2–3 word anchors. Respect the word-count cap."
    )
    user = (
        f"Topic: {topic or 'article'}\n\nTasks:\n"
        + "\n".join(f"- {t}" for t in tasks)
        + f"\n\n---ARTICLE---\n{article_md.strip()}\n"
    )
    return claude.chat_complete(
        system,
        user,
        step_label="Final output repair (FAQ / links / length)",
        max_tokens=8192,
        temperature=0.35,
    ).strip()


def _update_metadata_counts(full_text: str, article_md: str, word_target: int | None) -> str:
    faq_n = len(faq_schema.extract_faq_pairs(article_md))
    ext_n = count_external_markdown_links(article_md)
    int_n = count_internal_link_placeholders(article_md)
    wc = editorial_input.count_article_words(article_md)
    text = full_text
    if "INTERNAL LINKS ADDED:" in text:
        text = re.sub(
            r"INTERNAL LINKS ADDED:\s*\d+",
            f"INTERNAL LINKS ADDED: {int_n}",
            text,
            count=1,
        )
    if faq_n >= 2:
        if "FAQ COUNT:" in text:
            text = re.sub(r"FAQ COUNT:\s*\d+", f"FAQ COUNT: {faq_n}", text, count=1)
        elif "---PUBLISHING METADATA" in text:
            text = text.replace(
                "STATUS: READY FOR CMS",
                f"FAQ COUNT: {faq_n}\nSTATUS: READY FOR CMS",
                1,
            )
        if "FAQ section:" in text:
            text = re.sub(
                r"FAQ section:\s*\[PASS / ADDED[^\]]*\]",
                "FAQ section: ADDED — pipeline",
                text,
                count=1,
            )
            text = re.sub(
                r"FAQ section:\s*\[PASS[^\]]*\]",
                "FAQ section: PASS",
                text,
                count=1,
            )
    if "EXTERNAL LINKS ADDED:" in text:
        text = re.sub(
            r"EXTERNAL LINKS ADDED:\s*\d+",
            f"EXTERNAL LINKS ADDED: {ext_n}",
            text,
            count=1,
        )
    elif ext_n and "INTERNAL LINKS ADDED:" in text:
        text = text.replace(
            "INTERNAL LINKS ADDED:",
            f"EXTERNAL LINKS ADDED: {ext_n}\nINTERNAL LINKS ADDED:",
            1,
        )
    if "ESTIMATED WORD COUNT:" in text:
        text = re.sub(
            r"ESTIMATED WORD COUNT:\s*[\d,]+",
            f"ESTIMATED WORD COUNT: {wc:,}",
            text,
            count=1,
        )
    elif word_target and "---PUBLISHING METADATA" in text:
        text = text.replace(
            "INTERNAL LINKS ADDED:",
            f"ESTIMATED WORD COUNT: {wc:,}\nINTERNAL LINKS ADDED:",
            1,
        )
    return text


def _load_faq_reference_markdown(client_id: str, run_id: str) -> str:
    """Best prior artifact to preserve FAQ Q&As from (fact-check, then draft)."""
    for step in ("fact_check", "draft"):
        try:
            raw = artifacts.load_artifact(client_id, run_id, step)
        except FileNotFoundError:
            continue
        body = (
            faq_schema.extract_corrected_article_body(raw)
            if step == "fact_check"
            else (raw or "").strip()
        )
        if faq_schema.extract_faq_pairs(body):
            return body
    return ""


def _preserve_faq_from_prior_steps(
    article: str,
    client_id: str,
    run_id: str,
    *,
    heading: str = "## Frequently Asked Questions",
) -> str:
    reference = _load_faq_reference_markdown(client_id, run_id)
    if not reference:
        return article
    restored = faq_schema.ensure_faq_from_reference(
        article, reference, heading=heading
    )
    if restored != article:
        before = len(faq_schema.extract_faq_pairs(article))
        after = len(faq_schema.extract_faq_pairs(restored))
        logger.info(
            "FAQ restored for %s/%s: %s -> %s question(s)",
            client_id,
            run_id,
            before,
            after,
        )
    return restored


def _load_source_urls(client_id: str, run_id: str) -> list[str]:
    chunks: list[str] = []
    for step in ("serp_research", "research", "fact_check"):
        try:
            chunks.append(artifacts.load_artifact(client_id, run_id, step))
        except FileNotFoundError:
            pass
    return extract_citable_urls(*chunks, exclude_host_substrings=("arsuno.ai",))


def enforce_final_output(
    final_output: str,
    client_id: str,
    run_id: str,
    *,
    allow_llm_repair: bool = False,
) -> str:
    """Inject FAQ + external links + JSON-LD. Optional LLM trim runs last only."""
    text = (final_output or "").strip()
    if not text:
        return final_output

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    if not isinstance(manual, dict):
        manual = {}
    word_target = editorial_input.word_count_target_from_manifest(manifest)
    topic = (manifest.get("topic") or manual.get("Topic") or "").strip()
    lang = editorial_input.article_language_from_manual(manual)
    faq_heading = editorial_input.faq_heading_for_language(lang)

    paa_faq = ""
    try:
        paa_faq = artifacts.load_artifact(client_id, run_id, "paa_faq_research")
    except FileNotFoundError:
        paa_faq = ""

    article = faq_schema.extract_final_article_body(text) or faq_schema.strip_publishing_metadata_block(text) or text
    # Undo pasted HTML/CSS templates (CTA shell, table preview) before anything
    # counts CTAs or words; real HTML CTAs are re-applied at the very end.
    from . import html_leak
    from .context_extractor import resolve_cta_href as _resolve_cta_href

    if html_leak.has_leaked_html(article):
        article = html_leak.strip_leaked_html(
            article, cta_href=_resolve_cta_href(client_id)
        )
        logger.warning(
            "final_output: removed leaked HTML/CSS template from article for %s/%s",
            client_id,
            run_id,
        )
    article = faq_schema.consolidate_faq_sections(
        article, heading=faq_heading, lang=lang
    )
    urls = _load_source_urls(client_id, run_id)

    from .context_extractor import extract_for_step_7

    clusters = extract_for_step_7(client_id).get("clusters") or []
    article = normalize_article_links(article, clusters)
    form_links = editorial_input.parse_form_internal_links(manual)
    if form_links:
        article = inject_form_internal_links(article, form_links)

    if _needs_faq(article, manual):
        article = inject_faq_template(
            article, topic, manual=manual, paa_faq_research=paa_faq
        )

    article = _preserve_faq_from_prior_steps(
        article, client_id, run_id, heading=faq_heading
    )

    if _needs_external(article, manual) and urls:
        article = inject_external_links_programmatic(article, urls)

    article = normalize_article_links(article, clusters)

    from .context_extractor import resolve_cta_href
    from . import cta_html

    cta_href = resolve_cta_href(client_id)
    article_lang = editorial_input.article_language_from_manual(manual)
    if not clusters:
        logger.warning(
            "no internal-link clusters parsed from %s/context/internal_links.md "
            "(missing file or unrecognised format): cluster links will not be added",
            client_id,
        )
    # The model sometimes skips CTAs entirely; guarantee at least two.
    from .context_extractor import extract_for_step_7 as _ctx7

    article, _ = ensure_min_ctas(
        article,
        cta_href=cta_href,
        lang=article_lang,
        cta_examples=_ctx7(client_id).get("cta_examples"),
    )
    # Keep CTAs as markdown through lint / trim / hard gates — HTML wrap is last.
    article = writing_format_enforce.enforce_article(
        article,
        stage="final",
        allow_llm_repair=allow_llm_repair,
        cta_href=cta_href,
        lang=article_lang,
    )
    if form_links:
        article = inject_form_internal_links(article, form_links)

    if word_target:
        _, high = editorial_input.word_count_bounds(word_target)
        if allow_llm_repair and editorial_input.count_article_words(article) > high:
            try:
                article = _trim_article_llm(article, word_target, topic)
            except Exception:
                logger.exception(
                    "final_output trim failed for %s/%s", client_id, run_id
                )

    article = _preserve_faq_from_prior_steps(
        article, client_id, run_id, heading=faq_heading
    )
    article = faq_schema.consolidate_faq_sections(
        article, heading=faq_heading, lang=lang
    )
    article = faq_schema.enforce_faq_answer_length(article, heading=faq_heading)

    if faq_schema.FINAL_OUTPUT_START in text:
        text = faq_schema.replace_final_article_body(text, article)
    elif faq_schema.FINAL_ARTICLE_START in text:
        text = faq_schema.replace_final_article_body(text, article)
    elif article.strip():
        text = faq_schema.wrap_final_article(article)

    text = faq_schema.strip_publishing_metadata_block(text)
    if (
        faq_schema.FINAL_OUTPUT_START not in text
        and faq_schema.FINAL_ARTICLE_START not in text
        and article.strip()
    ):
        text = faq_schema.wrap_final_article(article)

    text = faq_schema.ensure_faq_schema_block(text)

    from . import hard_gates

    text = hard_gates.enforce_article_gates(
        text,
        client_id=client_id,
        run_id=run_id,
        stage="final",
        allow_llm_repair=allow_llm_repair,
        raise_on_fail=True,
    )

    # After all LLM/markdown repairs: wrap markdown CTAs in the workspace HTML shell.
    body = faq_schema.extract_final_article_body(text) or text
    # The repairs above may have added, moved or duplicated CTAs: exactly two,
    # never in the opening, before the HTML shell is applied.
    body_policy, _ = ensure_min_ctas(
        body,
        cta_href=cta_href,
        lang=article_lang,
        cta_examples=_ctx7(client_id).get("cta_examples"),
    )
    wrapped = cta_html.apply_workspace_cta_html(
        body_policy, client_id=client_id, cta_href=cta_href
    )
    if wrapped != body:
        if faq_schema.FINAL_OUTPUT_START in text or faq_schema.FINAL_ARTICLE_START in text:
            text = faq_schema.replace_final_article_body(text, wrapped)
        else:
            text = wrapped
        logger.info(
            "workspace HTML CTAs applied for %s (%s markdown CTA block(s))",
            client_id,
            len(cta_html.find_markdown_ctas(body, cta_href=cta_href)),
        )
    return text
