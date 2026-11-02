"""Prompt assembly for Anthropic/OpenRouter prompt caching (Phase 2).

Message layout for every Claude pipeline step:

1. **System block 0** — workspace files marked ``cache_control``. Lean steps
   (topic card, SERP analysis, research audit, meta) get company context,
   personas, and glossary only. Writing steps also get brand voice, guidelines,
   CTA, and clusters.
2. **System block 1** — writing steps: derived brand-voice / CTA / format rules
   (plus the French language block when the run is French). Lean steps skip
   brand-voice and CTA rules; French still gets the language block.
3. **User block A** — only the run documents that step needs, with a
   ``cache_control`` breakpoint after it. Later steps get a short research
   summary instead of the raw SERP / ATP / PAA dumps. The outline gets the
   brief, not the raw SERP analysis.
4. **User block B** — step prompt plus anything unique to that call.

Varying content (timestamps, run IDs, step numbers, form notices) must never
appear before the breakpoint. Cached input tokens are billed at a small fraction
of uncached input on Anthropic models via OpenRouter.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from . import artifacts
from . import config
from . import french_language
from . import prompts
from .context_extractor import extract_for_step_5, extract_for_step_7

logger = logging.getLogger(__name__)

# Catalog of run artifacts (stable header names). Per-step subsets live in STEP_SHARED_DOCS.
SHARED_DOC_SPECS: tuple[tuple[str, str], ...] = (
    ("TOPIC CARD", "topic_card"),
    ("SERP ANALYSIS", "research"),
    ("ATP TOPIC RESEARCH", "atp_topic_research"),
    ("PAA FAQ RESEARCH", "paa_faq_research"),
    ("RESEARCH AUDIT", "research_audit"),
    ("ASSIGNMENT BRIEF", "assignment_brief"),
)

# Virtual artifact: condensed SERP analysis + audit highlights + source URLs.
RESEARCH_SUMMARY_KEY = "research_summary"

# Only the documents each Claude step actually needs. Missing artifacts are omitted.
STEP_SHARED_DOCS: dict[str, tuple[tuple[str, str], ...]] = {
    "topic_card": (),
    "research": (("TOPIC CARD", "topic_card"),),
    "research_audit": (
        ("TOPIC CARD", "topic_card"),
        ("SERP ANALYSIS", "research"),
        ("ATP TOPIC RESEARCH", "atp_topic_research"),
        ("PAA FAQ RESEARCH", "paa_faq_research"),
    ),
    "assignment_brief": (
        ("TOPIC CARD", "topic_card"),
        ("RESEARCH SUMMARY", RESEARCH_SUMMARY_KEY),
        ("RESEARCH AUDIT", "research_audit"),
    ),
    "outline": (
        ("ASSIGNMENT BRIEF", "assignment_brief"),
        ("RESEARCH SUMMARY", RESEARCH_SUMMARY_KEY),
    ),
    "draft": (
        ("ASSIGNMENT BRIEF", "assignment_brief"),
        ("RESEARCH SUMMARY", RESEARCH_SUMMARY_KEY),
        ("RESEARCH AUDIT", "research_audit"),
    ),
    "fact_check": (("TOPIC CARD", "topic_card"),),
    "meta_seo": (),
    "supporting_posts": (
        ("RESEARCH AUDIT", "research_audit"),
        ("ATP TOPIC RESEARCH", "atp_topic_research"),
    ),
}

# Topic card, SERP analysis, audit, and meta do not need brand-voice / CTA / format rules.
LEAN_STEPS: frozenset[str] = frozenset(
    {"topic_card", "research", "research_audit", "meta_seo", "fact_check"}
)

# First cached system block — identical on every step so lean and writing calls share it.
LEAN_CONTEXT_FILES: tuple[str, ...] = (
    "context.md",
    "personas.md",
    "french_glossary.md",
)

# Extra workspace files for writing steps (second cached system block, with brand/CTA rules).
WRITING_CONTEXT_FILES: tuple[str, ...] = (
    "brand_voice.md",
    "writing_guidelines.md",
    "cta_guidelines.md",
    "internal_links.md",
)

_CLIENT_CONTEXT_FILES: tuple[str, ...] = LEAN_CONTEXT_FILES + WRITING_CONTEXT_FILES

_HEADING_RE = re.compile(r"(?m)^#{1,3}\s+(.+?)\s*$")
_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")
_SERP_SUMMARY_HEADINGS = (
    "snapshot",
    "competitor benchmarks",
    "content gaps",
    "briefing hooks",
    "external sources",
)
_AUDIT_SUMMARY_HEADINGS = (
    "audit summary",
    "approved case study",
    "approved keywords",
    "approved faq",
    "approved supporting",
    "stats & figures",
    "flagged",
)
RESEARCH_SUMMARY_MAX_CHARS = 6000
_SECTION_MAX_CHARS = 1600

# Approximate chars/token for prefix-size warnings (Anthropic Sonnet min ~1024).
_CHARS_PER_TOKEN_EST = 4
_DEFAULT_MIN_CACHE_TOKENS = 1024

CACHE_CONTROL_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}


@dataclass(frozen=True)
class CachedPrompt:
    """Structured Claude request with a cacheable prefix."""

    system_text: str
    shared_docs_text: str
    unique_text: str
    session_id: str
    step_label: str = "pipeline step"
    enable_cache: bool = True
    workspace_text: str = ""

    def with_unique(self, unique_text: str, *, step_label: str | None = None) -> CachedPrompt:
        return replace(
            self,
            unique_text=unique_text,
            step_label=step_label or self.step_label,
        )

    @property
    def prefix_char_count(self) -> int:
        return len(self.workspace_text) + len(self.system_text) + len(self.shared_docs_text)

    @property
    def prefix_token_estimate(self) -> int:
        return max(1, self.prefix_char_count // _CHARS_PER_TOKEN_EST)

    def cache_control(self) -> dict[str, str] | None:
        if not self.enable_cache:
            return None
        ctrl = dict(CACHE_CONTROL_EPHEMERAL)
        ttl = (getattr(config, "PROMPT_CACHE_TTL", None) or "").strip()
        if ttl:
            ctrl["ttl"] = ttl
        return ctrl

    def system_blocks(self) -> list[dict[str, Any]]:
        ctrl = self.cache_control()
        blocks: list[dict[str, Any]] = []
        if (self.workspace_text or "").strip():
            workspace: dict[str, Any] = {"type": "text", "text": self.workspace_text}
            if ctrl is not None:
                workspace["cache_control"] = ctrl
            blocks.append(workspace)
        if (self.system_text or "").strip():
            block: dict[str, Any] = {"type": "text", "text": self.system_text}
            if ctrl is not None:
                block["cache_control"] = ctrl
            blocks.append(block)
        if not blocks:
            blocks.append({"type": "text", "text": "You are an editorial assistant."})
        return blocks

    def user_content_blocks(self) -> list[dict[str, Any]]:
        unique = {"type": "text", "text": self.unique_text}
        if not (self.shared_docs_text or "").strip():
            return [unique]
        shared: dict[str, Any] = {"type": "text", "text": self.shared_docs_text}
        ctrl = self.cache_control()
        if ctrl is not None:
            shared["cache_control"] = ctrl
        return [shared, unique]

    def messages(self) -> list[dict[str, Any]]:
        return [{"role": "user", "content": self.user_content_blocks()}]


def session_id_for_run(client_id: str, run_id: str) -> str:
    """Sticky OpenRouter routing key (max 256 chars)."""
    raw = f"article:{client_id}:{run_id}"
    return raw[:256]


def _load_artifact_body(client_id: str, run_id: str, step_name: str) -> str:
    try:
        text = artifacts.load_artifact(client_id, run_id, step_name)
    except FileNotFoundError:
        return ""
    return (text or "").strip()


def context_files_for_step(step_name: str) -> tuple[str, ...]:
    """First system block is always the lean file set (shared cache across steps)."""
    return LEAN_CONTEXT_FILES


def uses_writing_rules(step_name: str) -> bool:
    return step_name not in LEAN_STEPS


def build_workspace_files_block(
    client_id: str, filenames: tuple[str, ...] | None = None
) -> str:
    """Lean workspace files — first cached system block, identical every step."""
    files = filenames if filenames is not None else LEAN_CONTEXT_FILES
    parts: list[str] = [
        "You are an editorial assistant for a client content pipeline. "
        "Follow the client context and writing rules below for every task. "
        "The step-specific instructions appear in the final user message block.",
        "",
        "=== CLIENT CONTEXT FILES ===",
    ]
    file_block = artifacts.load_context_files(client_id, files)
    if file_block.strip():
        parts.append(file_block)
    parts.append("=== END CLIENT CONTEXT FILES ===")
    return "\n".join(parts).strip() + "\n"


def build_client_rules_prompt(client_id: str) -> str:
    """Brand-voice / CTA / format rules — second cached system block (writing steps)."""
    parts: list[str] = ["=== CLIENT WRITING RULES ==="]
    writing_files = artifacts.load_context_files(client_id, WRITING_CONTEXT_FILES)
    if writing_files.strip():
        parts.append(writing_files)

    extracted5 = extract_for_step_5(client_id)
    va_lines: list[str] = []
    for item in extracted5.get("voice_attributes") or []:
        if isinstance(item, dict):
            name = item.get("name") or ""
            va_lines.append(f"- {name}")
            if item.get("instruction"):
                va_lines.append(f'  Instruction: {item["instruction"]}')
            if item.get("right"):
                va_lines.append(f'  Right example: {item["right"]}')
            if item.get("wrong"):
                va_lines.append(f'  Wrong example: {item["wrong"]}')
        else:
            va_lines.append(f"- {item}")
    voice_attrs_block = "\n".join(va_lines) if va_lines else "None specified"
    bt = extracted5.get("blog_tone")
    blog_tone_line = (
        f"BLOG POST TONE (for blog articles): {bt.get('tone', '')}\n"
        if isinstance(bt, dict) and bt.get("tone")
        else ""
    )
    vocab = ""
    if extracted5.get("do_not_write_like"):
        vocab = "\n".join(
            f'  Instead of "{dnt}": use "{dw}"'
            for dnt, dw in zip(
                extracted5.get("do_not_write_like") or [],
                extracted5.get("do_write_like") or [],
            )
        )
    else:
        vocab = "None specified"

    company = (extracted5.get("company_name") or "Unknown").upper()
    parts.append(
        f"---BRAND VOICE RULES FOR {company}---\n"
        "CRITICAL: You MUST follow these rules. Do not deviate.\n"
        f"{blog_tone_line}"
        "BANNED WORDS (do not use any of these):\n"
        f"{', '.join(extracted5['banned_words']) if extracted5.get('banned_words') else 'None specified'}\n"
        "VOICE ATTRIBUTES (write with these — each line may include Right/Wrong examples):\n"
        f"{voice_attrs_block}\n"
        "TARGET PERSONAS (write for these people):\n"
        f"{', '.join(extracted5['persona_names']) if extracted5.get('persona_names') else 'Unknown'}\n"
        "VOCABULARY PREFERENCES:\n"
        "Instead of generic corporate language, use:\n"
        f"{vocab}\n"
        "---END BRAND VOICE RULES---\n"
    )

    extracted7 = extract_for_step_7(client_id)
    clusters = extracted7.get("clusters") or []
    cluster_lines = (
        "\n".join(f"{i + 1}. {cluster}" for i, cluster in enumerate(clusters))
        if clusters
        else "No clusters defined"
    )
    cta_examples = extracted7.get("cta_examples") or []
    cta_example_lines = (
        "\n".join(f"- {ex}" for ex in cta_examples)
        if cta_examples
        else "- (follow CTA guidelines tone; link to the project CTA URL below)"
    )
    cta_href = (extracted7.get("cta_href") or "").strip() or "/contact"
    website = (extracted7.get("website") or "").strip()
    html_note = (
        "Workspace HTML CTA template: YES — still write markdown CTAs "
        "(bold heading + description + markdown link). The pipeline wraps them "
        "in the workspace HTML shell after generation; only the three statements "
        "change per article; the contact URL stays fixed.\n"
        if extracted7.get("has_cta_html_template")
        else "Workspace HTML CTA template: NO — leave CTAs as markdown links.\n"
    )
    parts.append(
        "---INTERNAL LINKING & CTA (client-level)---\n"
        "These are the content clusters for this client:\n"
        f"{cluster_lines}\n"
        "When adding extra cluster placeholders, reference only these cluster names.\n"
        f"CTA Philosophy: {extracted7.get('cta_philosophy') or ''}\n"
        "CTA examples:\n"
        f"{cta_example_lines}\n"
        f"Project live site: {website or '[not set in context.md]'}\n"
        f"Required CTA markdown href (use exactly): {cta_href}\n"
        f"{html_note}"
        "---END INTERNAL LINKING & CTA---\n"
    )

    parts.append(prompts.WRITING_FORMAT_BLOCK.strip())
    parts.append("=== END CLIENT WRITING RULES ===")
    return "\n\n".join(parts).strip() + "\n"


def build_client_system_prompt(client_id: str) -> str:
    """Full system prefix (workspace files + rules) — identical for every step."""
    return (
        build_workspace_files_block(client_id).rstrip()
        + "\n\n"
        + build_client_rules_prompt(client_id).lstrip()
    )


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    raw = (text or "").strip()
    if not raw:
        return []
    matches = list(_HEADING_RE.finditer(raw))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        sections.append((match.group(1).strip(), raw[start:end].strip()))
    return sections


def _wanted_sections(
    text: str, wanted: tuple[str, ...], *, max_chars: int = _SECTION_MAX_CHARS
) -> list[str]:
    out: list[str] = []
    for heading, body in _split_markdown_sections(text):
        key = heading.lower()
        if not any(token in key for token in wanted):
            continue
        clipped = body.strip()
        if len(clipped) > max_chars:
            clipped = clipped[:max_chars].rsplit("\n", 1)[0] + "\n[… truncated …]"
        out.append(f"## {heading}\n{clipped}")
    return out


def _source_urls(*texts: str, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for raw in texts:
        for match in _URL_RE.finditer(raw or ""):
            url = match.group(0).rstrip(".,;:")
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                return urls
    return urls


def build_research_summary(client_id: str, run_id: str) -> str:
    """Condensed SERP analysis + audit highlights for later steps (not the raw research)."""
    analysis = _load_artifact_body(client_id, run_id, "research")
    audit = _load_artifact_body(client_id, run_id, "research_audit")
    serp = _load_artifact_body(client_id, run_id, "serp_research")
    parts: list[str] = [
        "=== RESEARCH SUMMARY (condensed — not the raw SERP / ATP / PAA documents) ===",
    ]
    serp_bits = _wanted_sections(analysis, _SERP_SUMMARY_HEADINGS)
    if serp_bits:
        parts.append("---FROM SERP ANALYSIS---")
        parts.extend(serp_bits)
    audit_bits = _wanted_sections(audit, _AUDIT_SUMMARY_HEADINGS, max_chars=2000)
    if audit_bits:
        parts.append("---FROM RESEARCH AUDIT---")
        parts.extend(audit_bits)
    urls = _source_urls(analysis, audit, serp)
    if urls:
        parts.append("---SOURCE URLS---")
        parts.extend(f"- {url}" for url in urls)
    if len(parts) == 1:
        return ""
    text = "\n\n".join(parts).strip()
    if len(text) > RESEARCH_SUMMARY_MAX_CHARS:
        text = text[:RESEARCH_SUMMARY_MAX_CHARS].rsplit("\n", 1)[0] + "\n[… truncated …]"
    return text + "\n"


def build_shared_documents_block(
    client_id: str, run_id: str, step_name: str = ""
) -> str:
    """Run documents this step needs (user block A). Missing artifacts are skipped."""
    specs = STEP_SHARED_DOCS.get(step_name, ())
    if not specs:
        return ""
    sections: list[str] = [
        "=== SHARED RUN DOCUMENTS (only what this step needs) ===",
    ]
    for label, artifact_name in specs:
        if artifact_name == RESEARCH_SUMMARY_KEY:
            body = build_research_summary(client_id, run_id)
        else:
            body = _load_artifact_body(client_id, run_id, artifact_name)
        if not (body or "").strip():
            continue
        sections.append(f"---{label}---\n{body.strip()}\n")
    if len(sections) == 1:
        return ""
    sections.append("=== END SHARED RUN DOCUMENTS ===")
    return "\n\n".join(sections).strip() + "\n"


def build_cached_prompt(
    *,
    client_id: str,
    run_id: str,
    step_prompt: str,
    unique_suffix: str,
    step_label: str,
    enable_cache: bool | None = None,
    lang: str = "en",
    step_name: str = "",
) -> CachedPrompt:
    """Assemble system + shared docs + step prompt / unique suffix.

    French runs (``lang="fr"``) get the French language rule, banned-word list and
    brand glossary in the second cached system block (workspace files stay first so
    the file prefix still cache-hits), and a short French reminder after the step
    prompt (the last instruction the model reads).
    """
    if enable_cache is None:
        enable_cache = bool(getattr(config, "PROMPT_CACHE_ENABLED", True))

    workspace_text = build_workspace_files_block(
        client_id, context_files_for_step(step_name)
    )
    system_text = ""
    if uses_writing_rules(step_name):
        system_text = build_client_rules_prompt(client_id)
    glossary = None
    if (lang or "").lower() == "fr":
        glossary = french_language.load_glossary(client_id)
        french_block = french_language.system_block(glossary)
        system_text = (
            french_block + "\n" + system_text if system_text else french_block
        )
    shared = build_shared_documents_block(client_id, run_id, step_name)
    unique = (step_prompt or "").rstrip()
    if glossary is not None:
        # Fixed English headings in the step templates (H2: Frequently Asked Questions)
        # are copied by the model: show the French headings instead.
        unique = french_language.localize_step_prompt(unique)
    suffix = (unique_suffix or "").strip()
    if suffix:
        unique = f"{unique}\n\n---STEP-SPECIFIC INPUT---\n{suffix}\n" if unique else suffix
    if glossary is not None:
        unique = f"{unique}\n\n{french_language.step_directive(step_name, glossary)}".strip()
    if not unique.strip():
        unique = "(No additional step-specific input.)\n"

    prompt = CachedPrompt(
        system_text=system_text,
        shared_docs_text=shared,
        unique_text=unique if unique.endswith("\n") else unique + "\n",
        session_id=session_id_for_run(client_id, run_id),
        step_label=step_label,
        enable_cache=enable_cache,
        workspace_text=workspace_text,
    )
    min_tokens = int(getattr(config, "PROMPT_CACHE_MIN_TOKENS", _DEFAULT_MIN_CACHE_TOKENS) or _DEFAULT_MIN_CACHE_TOKENS)
    if prompt.enable_cache and prompt.prefix_token_estimate < min_tokens:
        logger.warning(
            "%s: cacheable prefix ~%s tokens (chars=%s) may be below provider minimum %s — "
            "OpenRouter/Anthropic will not cache short prefixes",
            step_label,
            prompt.prefix_token_estimate,
            prompt.prefix_char_count,
            min_tokens,
        )
    else:
        logger.debug(
            "%s: cache prefix ~%s tokens (system=%s shared=%s unique=%s session=%s)",
            step_label,
            prompt.prefix_token_estimate,
            len(workspace_text) + len(system_text),
            len(shared),
            len(prompt.unique_text),
            prompt.session_id,
        )
    return prompt


# Track sessions that have completed at least one cached call (warm).
_warmed_sessions: set[str] = set()


def mark_session_warmed(session_id: str) -> None:
    if session_id:
        _warmed_sessions.add(session_id)


def is_session_warmed(session_id: str) -> bool:
    return bool(session_id) and session_id in _warmed_sessions


def clear_warmed_sessions() -> None:
    """Test helper."""
    _warmed_sessions.clear()


__all__ = [
    "CACHE_CONTROL_EPHEMERAL",
    "LEAN_STEPS",
    "RESEARCH_SUMMARY_KEY",
    "SHARED_DOC_SPECS",
    "STEP_SHARED_DOCS",
    "CachedPrompt",
    "build_cached_prompt",
    "build_client_rules_prompt",
    "build_client_system_prompt",
    "build_research_summary",
    "build_shared_documents_block",
    "build_workspace_files_block",
    "context_files_for_step",
    "clear_warmed_sessions",
    "is_session_warmed",
    "mark_session_warmed",
    "session_id_for_run",
]
