"""Repair final_output artifacts: FAQ section, external links, word count, JSON-LD."""

from __future__ import annotations

import logging
import re

from . import artifacts
from . import editorial_input
from . import faq_schema
from . import writing_format_enforce
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")
_SKIP_URL_SUBSTR = ("youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com/")

_FAQ_TEMPLATES: tuple[tuple[str, str], ...] = (
    (
        "How long does it take to implement AI CV screening?",
        "Most agencies run a pilot in 2–4 weeks: integrate with your ATS or inbox, "
        "train ranking rules on 2–3 live roles, then roll out team-wide. Full ROI "
        "usually shows within the first placement cycle after go-live.",
    ),
    (
        "Will AI replace our recruiters?",
        "No — AI removes repetitive CV triage so consultants spend time on client "
        "relationships, interviews, and closing. The best setups keep humans in control "
        "of every shortlist decision.",
    ),
    (
        "Is AI screening GDPR-compliant for candidate data?",
        "Yes, when you use a processor with encryption, audit logs, lawful basis "
        "documented in privacy notices, and human review of automated decisions. "
        "Verify retention limits and cross-border hosting with your DPO before launch.",
    ),
    (
        "How much faster are shortlists with AI screening?",
        "Agencies typically cut time-to-shortlist by 40–60% on high-volume roles; "
        "case studies report up to 2× faster project delivery when screening was the bottleneck.",
    ),
    (
        "How does AI CV screening differ from keyword filters?",
        "Keyword filters miss context (titles vs skills). NLP-based screening scores fit "
        "against the full brief, explains why a candidate ranked, and adapts to "
        "recruitment terminology — not just exact string matches.",
    ),
    (
        "What ROI should we expect from recruitment AI automation?",
        "Track time-to-shortlist, placements per consultant, and repeat-business rate. "
        "Strong implementations improve client satisfaction scores while holding "
        "submission quality steady or better.",
    ),
)


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


def inject_faq_template(article: str, topic: str = "") -> str:
    """Insert a minimal FAQ block before Conclusion when the model skipped it."""
    if len(faq_schema.extract_faq_pairs(article)) >= 2:
        return article
    faq_lines = ["\n## Frequently Asked Questions\n"]
    for q, a in _FAQ_TEMPLATES[:6]:
        faq_lines.append(f"### {q}\n\n{a}\n")
    faq_block = "\n".join(faq_lines)
    m = re.search(r"\n##\s+Conclusion\b", article, re.I)
    if m:
        return article[: m.start()] + "\n" + faq_block + article[m.start() :]
    return article.rstrip() + "\n" + faq_block + "\n"


def _trim_article_llm(article_md: str, target: int, topic: str) -> str:
    low, high = editorial_input.word_count_bounds(target)
    current = editorial_input.count_article_words(article_md)
    if current <= high:
        return article_md
    user = (
        f"Topic: {topic or 'article'}\n"
        f"Body prose (FAQ excluded) is {current:,} words. Editor target: {target:,} "
        f"(acceptable {low:,}–{high:,} — do not exceed {high:,}).\n\n"
        f"Shorten main sections only; keep all H2 headings except you may tighten prose. "
        f"Keep the FAQ section and inline links (external [words](https://…), "
        f"internal [words](INTERNAL:…)). FAQ does not count toward the limit.\n"
        f"Keep **every** H3 question under ## Frequently Asked Questions from the input. "
        f"Do not drop or merge FAQ items.\n"
        f"Output ONLY the full markdown article.\n\n---ARTICLE---\n{article_md.strip()}\n"
    )
    return claude.chat_complete(
        "You are a publishing editor trimming articles to an exact word budget.",
        user,
        step_label="Final output trim",
        max_tokens=8192,
        temperature=0.35,
    ).strip()


def _repair_article_with_llm(
    article_md: str,
    *,
    add_faq: bool,
    add_external: bool,
    urls: list[str],
    topic: str,
    word_target: int | None,
) -> str:
    current = editorial_input.count_article_words(article_md)
    tasks: list[str] = []
    if word_target:
        low, high = editorial_input.word_count_bounds(word_target)
        tasks.append(
            f"Body prose (FAQ excluded) MUST be {low:,}–{high:,} words (form target "
            f"{word_target:,}). Current body: {current:,}. Trim filler before adding FAQ/links."
        )
    if add_faq:
        tasks.append(
            "Add `## Frequently Asked Questions` with 5–7 H3 Q&As before the conclusion."
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
    article: str, client_id: str, run_id: str
) -> str:
    reference = _load_faq_reference_markdown(client_id, run_id)
    if not reference:
        return article
    restored = faq_schema.ensure_faq_from_reference(article, reference)
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

    article = faq_schema.extract_final_article_body(text) or text
    urls = _load_source_urls(client_id, run_id)

    from .context_extractor import extract_for_step_7

    clusters = extract_for_step_7(client_id).get("clusters") or []
    article = normalize_article_links(article, clusters)

    if _needs_faq(article, manual):
        article = inject_faq_template(article, topic)

    article = _preserve_faq_from_prior_steps(article, client_id, run_id)

    if _needs_external(article, manual) and urls:
        article = inject_external_links_programmatic(article, urls)

    article = normalize_article_links(article, clusters)

    article = writing_format_enforce.enforce_article(
        article,
        stage="final",
        allow_llm_repair=allow_llm_repair,
    )

    if word_target:
        _, high = editorial_input.word_count_bounds(word_target)
        if allow_llm_repair and editorial_input.count_article_words(article) > high:
            try:
                article = _trim_article_llm(article, word_target, topic)
            except Exception:
                logger.exception(
                    "final_output trim failed for %s/%s", client_id, run_id
                )

    article = _preserve_faq_from_prior_steps(article, client_id, run_id)

    if faq_schema.FINAL_ARTICLE_START in text:
        text = faq_schema.replace_final_article_body(text, article)
    elif article.strip():
        text = article

    text = _update_metadata_counts(text, article, word_target)
    return faq_schema.ensure_faq_schema_block(text)
