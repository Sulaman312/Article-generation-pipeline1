"""Prompt assembly for Anthropic/OpenRouter prompt caching (Phase 2).

Message layout for every Claude pipeline step:

1. **System** — client context only (identical across all steps for a client):
   company context, personas, brand voice, banned words, writing guidelines,
   format guidelines, CTA guidelines, clusters.
2. **User block A** — shared run documents in a fixed order, with a
   ``cache_control`` breakpoint after it.
3. **User block B** — step prompt (01_…08_ / audit / supporting) plus anything
   unique to that call (IDs, notices, outlines, drafts, word-count overrides).

Varying content (timestamps, run IDs, step numbers, form notices) must never
appear before the breakpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from . import artifacts
from . import config
from . import prompts
from .context_extractor import extract_for_step_5, extract_for_step_7

logger = logging.getLogger(__name__)

# Fixed shared-document order (user block A). Stable headers — no step numbers.
SHARED_DOC_SPECS: tuple[tuple[str, str], ...] = (
    ("TOPIC CARD", "topic_card"),
    ("SERP ANALYSIS", "research"),
    ("ATP TOPIC RESEARCH", "atp_topic_research"),
    ("PAA FAQ RESEARCH", "paa_faq_research"),
    ("RESEARCH AUDIT", "research_audit"),
    ("ASSIGNMENT BRIEF", "assignment_brief"),
)

_MISSING = "[not available yet]"

# Client context files in a stable declaration order (system prefix).
_CLIENT_CONTEXT_FILES: tuple[str, ...] = (
    "context.md",
    "personas.md",
    "brand_voice.md",
    "writing_guidelines.md",
    "cta_guidelines.md",
    "internal_links.md",
)

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

    def with_unique(self, unique_text: str, *, step_label: str | None = None) -> CachedPrompt:
        return replace(
            self,
            unique_text=unique_text,
            step_label=step_label or self.step_label,
        )

    @property
    def prefix_char_count(self) -> int:
        return len(self.system_text) + len(self.shared_docs_text)

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
        block: dict[str, Any] = {"type": "text", "text": self.system_text}
        ctrl = self.cache_control()
        if ctrl is not None:
            block["cache_control"] = ctrl
        return [block]

    def user_content_blocks(self) -> list[dict[str, Any]]:
        shared: dict[str, Any] = {"type": "text", "text": self.shared_docs_text}
        ctrl = self.cache_control()
        if ctrl is not None:
            shared["cache_control"] = ctrl
        unique = {"type": "text", "text": self.unique_text}
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


def build_client_system_prompt(client_id: str) -> str:
    """Client-only system prompt — identical for every step of a client."""
    parts: list[str] = [
        "You are an editorial assistant for a client content pipeline. "
        "Follow the client context and writing rules below for every task. "
        "The step-specific instructions appear in the final user message block.",
        "",
        "=== CLIENT CONTEXT (identical for all pipeline steps) ===",
    ]

    file_block = artifacts.load_context_files(client_id, _CLIENT_CONTEXT_FILES)
    if file_block.strip():
        parts.append(file_block)

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
        "---END INTERNAL LINKING & CTA---\n"
    )

    parts.append(prompts.WRITING_FORMAT_BLOCK.strip())
    parts.append("=== END CLIENT CONTEXT ===")
    return "\n\n".join(parts).strip() + "\n"


def build_shared_documents_block(client_id: str, run_id: str) -> str:
    """Fixed-order shared run docs (user block A). Empty slots use a stable placeholder."""
    sections: list[str] = [
        "=== SHARED RUN DOCUMENTS (fixed order — cache breakpoint follows) ===",
    ]
    for label, step_name in SHARED_DOC_SPECS:
        body = _load_artifact_body(client_id, run_id, step_name) or _MISSING
        sections.append(f"---{label}---\n{body}\n")
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
) -> CachedPrompt:
    """Assemble system + shared docs + step prompt / unique suffix."""
    if enable_cache is None:
        enable_cache = bool(getattr(config, "PROMPT_CACHE_ENABLED", True))

    system_text = build_client_system_prompt(client_id)
    shared = build_shared_documents_block(client_id, run_id)
    unique = (step_prompt or "").rstrip()
    suffix = (unique_suffix or "").strip()
    if suffix:
        unique = f"{unique}\n\n---STEP-SPECIFIC INPUT---\n{suffix}\n" if unique else suffix
    if not unique.strip():
        unique = "(No additional step-specific input.)\n"

    prompt = CachedPrompt(
        system_text=system_text,
        shared_docs_text=shared,
        unique_text=unique if unique.endswith("\n") else unique + "\n",
        session_id=session_id_for_run(client_id, run_id),
        step_label=step_label,
        enable_cache=enable_cache,
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
            len(system_text),
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
    "SHARED_DOC_SPECS",
    "CachedPrompt",
    "build_cached_prompt",
    "build_client_system_prompt",
    "build_shared_documents_block",
    "clear_warmed_sessions",
    "is_session_warmed",
    "mark_session_warmed",
    "session_id_for_run",
]
