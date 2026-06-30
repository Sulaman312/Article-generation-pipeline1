"""Perplexity Sonar API — SERP-style research for the editorial pipeline.

Environment (see repo `env.example`):
  PERPLEXITY_API_KEY   — used for Step 2 (SERP) and Step 7 pre-scan (draft fact-check) when set
  PERPLEXITY_MODEL     — default `sonar` (options: sonar, sonar-pro, …)
  PERPLEXITY_API_URL   — default `https://api.perplexity.ai/v1/sonar`

Docs: https://docs.perplexity.ai/api-reference/sonar-post
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import config

logger = logging.getLogger(__name__)

_ALLOWED_MODELS = frozenset(
    {
        "sonar",
        "sonar-pro",
        "sonar-deep-research",
        "sonar-reasoning-pro",
    }
)

SERP_SYSTEM_PROMPT = """You are an elite SEO / SERP research assistant. Your job is to help a content
team understand what is winning in search for the topic described in the user's message.

Rules:
- Ground claims in current web results. Cite concrete page types (e.g. comparison site, vendor blog, gov).
- Cover: dominant content formats, common H2/H3 angles, entities and tools readers expect,
  typical depth, freshness signals, and obvious gaps or contradictions in the top results narrative.
- Include notable SERP features if inferable (PAA-style questions, listicles vs long guides, etc.).
- Do NOT invent specific ranking positions or traffic numbers.
- Prefer structured sections with clear headings using plain markdown (## and ###).
- End with a section `## Citable sources` — **5–10 bullets**. Each bullet must include:
  **Publisher or site name** — why it is authoritative for this topic — a **full `https://` URL**
  when available from search (no bare domains without scheme). These URLs will be used as outbound
  citations in the article."""


def _validated_model() -> str:
    m = (config.PERPLEXITY_MODEL or "sonar").strip().lower()
    if m not in _ALLOWED_MODELS:
        logger.warning("Unknown PERPLEXITY_MODEL %r — falling back to sonar", m)
        return "sonar"
    return m


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Perplexity returned non-JSON (starts: {raw[:120]!r})"
        ) from e
    if not isinstance(data, dict):
        raise ValueError("Perplexity returned unexpected JSON root type")
    return data


def _extract_message_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Perplexity response missing choices[]")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("Perplexity choice is not an object")
    msg = first.get("message")
    if not isinstance(msg, dict):
        raise ValueError("Perplexity choice missing message object")
    content = msg.get("content")
    if content is None:
        raise ValueError("Perplexity message missing content")
    return str(content).strip()


def build_serp_user_message(topic_card_text: str) -> str:
    """User message sent to Sonar — full topic card as grounding."""
    tc = (topic_card_text or "").strip()
    if not tc:
        tc = "[EMPTY — use seed keyword from workspace topic if inferable]"
    return (
        "Below is the **Topic Card** from our Step 1 pipeline (keyword, intent, angles, etc.).\n\n"
        "Perform SERP-oriented research for this article assignment: summarize what ranks, what "
        "patterns repeat, what readers likely expect, and where there is a defensible gap we can own.\n\n"
        "---TOPIC CARD---\n"
        f"{tc}\n"
        "---END TOPIC CARD---"
    )


def manual_serp_placeholder() -> str:
    """Saved when no API key — user pastes Perplexity output in the Run UI and saves."""
    return (
        "---SERP RESEARCH LAYER---\n"
        "SOURCE: **MANUAL** (Perplexity API key not configured on the server)\n\n"
        "Add `PERPLEXITY_API_KEY` to your `.env` (see `env.example`) to auto-generate this step.\n\n"
        "**What to do now:**\n"
        "1. In Perplexity (or your tool), run a SERP-focused research query using the same topic card "
        "you used in Step 1.\n"
        "2. Paste the full answer **below** the line.\n"
        "3. Click **Edit output** on this step, paste, save — then run **Step 3 (SERP analysis & gaps)**.\n\n"
        "---PASTE PERPLEXITY / SERP RESEARCH BELOW---\n\n"
    )


def run_sonar_serp(topic_card_text: str) -> str:
    """Call Perplexity Sonar; return formatted markdown artifact body."""
    if not config.PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")

    model = _validated_model()
    url = (config.PERPLEXITY_API_URL or "https://api.perplexity.ai/v1/sonar").strip()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": min(max(256, config.PERPLEXITY_MAX_TOKENS), 4000),
        "temperature": float(config.PERPLEXITY_TEMPERATURE or 0.15),
        "search_mode": "web",
        "return_related_questions": True,
        "messages": [
            {"role": "system", "content": SERP_SYSTEM_PROMPT},
            {"role": "user", "content": build_serp_user_message(topic_card_text)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        data = _post_json(url, headers, payload)
    except HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:
            pass
        raise ValueError(
            f"Perplexity HTTP {e.code}. {err_body or e.reason}"
        ) from e
    except URLError as e:
        raise ValueError(f"Perplexity network error: {e}") from e

    text = _extract_message_text(data)
    if not text:
        raise ValueError("Perplexity returned empty content")

    citations = data.get("citations")
    cit_lines: list[str] = []
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, str) and c.strip():
                cit_lines.append(c.strip())

    related = data.get("related_questions")
    rq_lines: list[str] = []
    if isinstance(related, list):
        for q in related:
            if isinstance(q, str) and q.strip():
                rq_lines.append(q.strip())

    out: list[str] = [
        "---SERP RESEARCH (PERPLEXITY)---",
        f"MODEL: {model}",
        "",
        "---MAIN RESPONSE---",
        text,
    ]
    if cit_lines:
        out.extend(["", "---CITATION URLS (from API)---"])
        out.extend(f"- {u}" for u in cit_lines[:40])
    if rq_lines:
        out.extend(["", "---RELATED QUESTIONS (from API)---"])
        out.extend(f"- {q}" for q in rq_lines[:25])
    return "\n".join(out) + "\n"


FACTCHECK_DRAFT_CHAR_LIMIT = 48_000

FACTCHECK_SYSTEM_PROMPT = """You are a meticulous research assistant with web search access.
The user message contains a **draft article** (not instructions). Support a human fact-checker:

- Pull out **specific, checkable factual claims** (numbers, dates, laws, product specs,
  "market leader" language, medical or legal assertions, version-specific tech claims).
- For high-risk items: say whether reputable current web sources **support**, **contradict**, or
  leave **unclear** — neutrally. Reference the draft with short quoted phrases, not long excerpts.
- Use markdown sections: ## Priority claims to verify, ## Possible conflicts or outdated framing,
  ## Suggested source types (not long pasted text).
- Do **not** rewrite the article. Do **not** present web snippets as legal or medical advice.
- If the draft is mostly opinion or generic guidance, say so briefly and list at most a few verify items.
"""


def build_factcheck_user_message(draft_markdown: str) -> str:
    d = (draft_markdown or "").strip()
    truncated = False
    if len(d) > FACTCHECK_DRAFT_CHAR_LIMIT:
        d = d[:FACTCHECK_DRAFT_CHAR_LIMIT] + "\n\n[… draft truncated for API limits …]\n"
        truncated = True
    note = " Draft was truncated for API limits." if truncated else ""
    return (
        "Perform a **web-grounded fact-check scan** of this draft for an editor."
        + note
        + "\n\n---DRAFT---\n"
        f"{d}\n"
        "---END DRAFT---"
    )


def run_sonar_draft_factcheck(draft_markdown: str) -> str:
    """Perplexity pass on the draft — signals for the Claude editor fact-check step."""
    if not config.PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")

    model = _validated_model()
    url = (config.PERPLEXITY_API_URL or "https://api.perplexity.ai/v1/sonar").strip()
    fc_max = min(max(512, config.PERPLEXITY_MAX_TOKENS), 2500)
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": fc_max,
        "temperature": min(float(config.PERPLEXITY_TEMPERATURE or 0.15), 0.25),
        "search_mode": "web",
        "return_related_questions": False,
        "messages": [
            {"role": "system", "content": FACTCHECK_SYSTEM_PROMPT},
            {"role": "user", "content": build_factcheck_user_message(draft_markdown)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        data = _post_json(url, headers, payload)
    except HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:
            pass
        raise ValueError(
            f"Perplexity HTTP {e.code}. {err_body or e.reason}"
        ) from e
    except URLError as e:
        raise ValueError(f"Perplexity network error: {e}") from e

    text = _extract_message_text(data)
    if not text:
        raise ValueError("Perplexity returned empty content")

    citations = data.get("citations")
    cit_lines: list[str] = []
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, str) and c.strip():
                cit_lines.append(c.strip())

    out: list[str] = [
        "---DRAFT FACT-CHECK SCAN (PERPLEXITY)---",
        f"MODEL: {model}",
        "",
        "---MAIN RESPONSE---",
        text,
    ]
    if cit_lines:
        out.extend(["", "---CITATION URLS (from API)---"])
        out.extend(f"- {u}" for u in cit_lines[:35])
    return "\n".join(out) + "\n"
