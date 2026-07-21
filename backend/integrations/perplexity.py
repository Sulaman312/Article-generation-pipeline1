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
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import config
from ..step_markers import wrap_step_artifact

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
- Do **not** open with a document title, cover line, or "research summary" banner — start with the first substantive ## section.
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
    from concurrent.futures import ThreadPoolExecutor, wait

    from backend import job_control

    job_control.raise_if_cancelled()
    body = json.dumps(payload).encode("utf-8")

    def _do_request() -> dict[str, Any]:
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

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_do_request)
        while True:
            job_control.raise_if_cancelled()
            done, _ = wait([future], timeout=0.4)
            if done:
                return future.result()


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


_SERP_PREAMBLE_RE = re.compile(
    r"^(?:#{1,3}\s+|\*\*)?SERP[- ]Oriented Research Summary\s*:[^\n]*\n+",
    re.IGNORECASE | re.MULTILINE,
)

_FACTCHECK_PREAMBLE_RE = re.compile(
    r"^(?:#{1,3}\s+|\*\*)?Web[- ]Grounded Fact[- ]Check Scan\s*:[^\n]*\n+",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_serp_display_preamble(text: str) -> str:
    """Drop redundant Perplexity title lines from SERP artifact bodies."""
    cleaned = _SERP_PREAMBLE_RE.sub("", (text or "").strip(), count=1)
    return cleaned.strip()


def _strip_factcheck_display_preamble(text: str) -> str:
    """Drop redundant Perplexity title lines from fact-check scan bodies."""
    cleaned = _FACTCHECK_PREAMBLE_RE.sub("", (text or "").strip(), count=1)
    return cleaned.strip()


def manual_serp_placeholder() -> str:
    """Saved when no API key — user pastes Perplexity output in the Run UI and saves."""
    body = (
        "SOURCE: **MANUAL** (Perplexity API key not configured on the server)\n\n"
        "Add `PERPLEXITY_API_KEY` to your `.env` (see `env.example`) to auto-generate this step.\n\n"
        "**What to do now:**\n"
        "1. In Perplexity (or your tool), run a SERP-focused research query using the same topic card "
        "you used in Step 1.\n"
        "2. Paste the full answer below.\n"
        "3. Click **Edit output** on this step, paste, save — then run **Step 3 (SERP analysis & gaps)**.\n"
    )
    return wrap_step_artifact("serp_research", body)


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

    text = _strip_serp_display_preamble(_extract_message_text(data))
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

    out: list[str] = [text]
    if cit_lines:
        out.extend(["", "## Citable sources (API)"])
        out.extend(f"- {u}" for u in cit_lines[:40])
    if rq_lines:
        out.extend(["", "## Related questions (API)"])
        out.extend(f"- {q}" for q in rq_lines[:25])
    return wrap_step_artifact("serp_research", "\n".join(out) + "\n")


def build_paa_faq_user_message(
    topic_card_text: str,
    *,
    serp_digest: str = "",
    research_doc: str = "",
    keyword_data: str = "",
    notes: str = "",
) -> str:
    """User message for the PAA / FAQ research Sonar call."""
    tc = (topic_card_text or "").strip() or "[EMPTY — topic card missing]"
    serp = (serp_digest or "").strip() or "[none]"
    analysis = (research_doc or "").strip() or "[none]"
    kw = (keyword_data or "").strip() or "[none]"
    ed_notes = (notes or "").strip() or "[none]"
    return (
        "Below is the **Topic Card** from our editorial pipeline (keyword, intent, angles, constraints).\n\n"
        "Optional context may follow (SERP digest, SERP analysis, keyword-tool data, and/or editor notes). "
        "Use it when present; do not invent missing SERP or keyword details.\n\n"
        "Task:\n"
        "1. Research **People Also Ask**, related questions, and FAQ-worthy objections for this topic.\n"
        "2. **Reconcile** web/SERP signals with keyword-tool data when provided:\n"
        "   - Keyword-tool export = demand anchor (volume, autocomplete breadth, question count).\n"
        "   - Web/PAA = phrasing and objection signals, not proof of volume when keyword data says otherwise.\n"
        "   - If seed keyword shows 0 or near-0 volume, flag it explicitly and downgrade unverified web questions.\n"
        "3. Produce a prioritized FAQ question bank for our article (featured snippets + on-page FAQ).\n"
        "4. Attach a citation for every non-INFERRED question. If you cannot cite it, mark INFERRED.\n"
        "5. Do not invent URLs or API strings — only cite what you fetched or what appears verbatim in "
        "## Related questions (API).\n\n"
        "---TOPIC CARD---\n"
        f"{tc}\n"
        "---END TOPIC CARD---\n\n"
        "---SERP RESEARCH DIGEST (optional)---\n"
        f"{serp}\n"
        "---END SERP DIGEST---\n\n"
        "---SERP ANALYSIS (optional)---\n"
        f"{analysis}\n"
        "---END SERP ANALYSIS---\n\n"
        "---KEYWORD DATA (optional)---\n"
        f"{kw}\n"
        "---END KEYWORD DATA---\n\n"
        "---EDITOR NOTES / LANGUAGE (optional)---\n"
        f"{ed_notes}\n"
        "---END NOTES---"
    )


def manual_paa_faq_placeholder() -> str:
    """Saved when no API key — editor pastes PAA / FAQ research in the Run UI."""
    body = (
        "SOURCE: **MANUAL** (Perplexity API key not configured on the server)\n\n"
        "Add `PERPLEXITY_API_KEY` to your `.env` (see `env.example`) to auto-generate this step.\n\n"
        "**What to do now:**\n"
        "1. In Perplexity (or your tool), research People Also Ask / related questions for this topic.\n"
        "2. Prefer questions with real SERP evidence; mark anything unproven as INFERRED.\n"
        "3. Paste a structured FAQ bank (6–8 questions when evidence supports it; fewer if thin).\n"
        "4. Click **Edit output** on this step, paste, save — then run **Assignment Brief**.\n"
    )
    return wrap_step_artifact("paa_faq_research", body)


def run_sonar_paa_faq(
    topic_card_text: str,
    *,
    serp_digest: str = "",
    research_doc: str = "",
    keyword_data: str = "",
    notes: str = "",
) -> str:
    """Call Perplexity Sonar for PAA / FAQ question bank; return markdown artifact body."""
    if not config.PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")

    from .. import prompts

    model = _validated_model()
    url = (config.PERPLEXITY_API_URL or "https://api.perplexity.ai/v1/sonar").strip()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": min(max(512, config.PERPLEXITY_MAX_TOKENS), 4000),
        "temperature": float(config.PERPLEXITY_TEMPERATURE or 0.15),
        "search_mode": "web",
        "return_related_questions": True,
        "messages": [
            {"role": "system", "content": prompts.PAA_FAQ_RESEARCH_PROMPT},
            {
                "role": "user",
                "content": build_paa_faq_user_message(
                    topic_card_text,
                    serp_digest=serp_digest,
                    research_doc=research_doc,
                    keyword_data=keyword_data,
                    notes=notes,
                ),
            },
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

    text = _extract_message_text(data).strip()
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

    # Pipeline owns ## Related questions (API) — append/overwrite with verbatim API strings.
    text = _ensure_related_questions_api_section(text, rq_lines)

    out: list[str] = [text]
    if cit_lines:
        out.extend(["", "## Citable sources (API)"])
        out.extend(f"- {u}" for u in cit_lines[:40])
    return wrap_step_artifact("paa_faq_research", "\n".join(out) + "\n")


def build_atp_topic_user_message(
    topic_card_text: str,
    *,
    serp_digest: str = "",
    research_doc: str = "",
    keyword_data: str = "",
    notes: str = "",
) -> str:
    """User message for AnswerThePublic-style topic research Sonar call."""
    tc = (topic_card_text or "").strip() or "[EMPTY — topic card missing]"
    serp = (serp_digest or "").strip() or "[none]"
    analysis = (research_doc or "").strip() or "[none]"
    kw = (keyword_data or "").strip() or "[none]"
    ed_notes = (notes or "").strip() or "[none]"
    return (
        "Below is the **Topic Card** from our editorial pipeline.\n\n"
        "Optional context may follow (SERP digest, SERP analysis, keyword-tool / AnswerThePublic "
        "paste, editor notes). Use it when present; do not invent missing volume or tool exports.\n\n"
        "Task:\n"
        "1. Produce an **AnswerThePublic-style** map: questions, prepositions, comparisons, "
        "alphabetical/long-tail variants grounded in current web/SERP signals.\n"
        "2. Identify **high-intent** questions and long-tails for the main article and a supporting "
        "blog cluster.\n"
        "3. Propose **3–5 supporting blog topics** with interlink anchors to/from the main article "
        "(plan only — do not write full posts).\n"
        "4. List keywords the **main** article should weave in naturally.\n"
        "5. Attach citations for non-INFERRED items. Never invent volumes or URLs.\n"
        "6. Reconcile with keyword-tool / ATP paste when provided — treat it as the demand anchor.\n\n"
        "---TOPIC CARD---\n"
        f"{tc}\n"
        "---END TOPIC CARD---\n\n"
        "---SERP RESEARCH DIGEST (optional)---\n"
        f"{serp}\n"
        "---END SERP DIGEST---\n\n"
        "---SERP ANALYSIS (optional)---\n"
        f"{analysis}\n"
        "---END SERP ANALYSIS---\n\n"
        "---KEYWORD / ANSWERTHEPUBLIC DATA (optional)---\n"
        f"{kw}\n"
        "---END KEYWORD DATA---\n\n"
        "---EDITOR NOTES / LANGUAGE (optional)---\n"
        f"{ed_notes}\n"
        "---END NOTES---"
    )


def manual_atp_topic_placeholder() -> str:
    """Saved when no API key — editor pastes ATP-style research in the Run UI."""
    body = (
        "SOURCE: **MANUAL** (Perplexity API key not configured on the server)\n\n"
        "Add `PERPLEXITY_API_KEY` to your `.env` (see `env.example`) to auto-generate this step.\n\n"
        "**What to do now:**\n"
        "1. In AnswerThePublic, Perplexity, or your keyword tool, research questions + long-tails "
        "for this topic.\n"
        "2. Paste a structured map: question groups, high-intent shortlist, long-tails, and "
        "3–5 supporting blog ideas with interlink anchors.\n"
        "3. Click **Edit output** on this step, paste, save — then continue the pipeline.\n"
    )
    return wrap_step_artifact("atp_topic_research", body)


def run_sonar_atp_topic(
    topic_card_text: str,
    *,
    serp_digest: str = "",
    research_doc: str = "",
    keyword_data: str = "",
    notes: str = "",
) -> str:
    """Call Perplexity Sonar for AnswerThePublic-style topic research."""
    if not config.PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")

    from .. import prompts

    model = _validated_model()
    url = (config.PERPLEXITY_API_URL or "https://api.perplexity.ai/v1/sonar").strip()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": min(max(512, config.PERPLEXITY_MAX_TOKENS), 4000),
        "temperature": float(config.PERPLEXITY_TEMPERATURE or 0.15),
        "search_mode": "web",
        "return_related_questions": True,
        "messages": [
            {"role": "system", "content": prompts.ATP_TOPIC_RESEARCH_PROMPT},
            {
                "role": "user",
                "content": build_atp_topic_user_message(
                    topic_card_text,
                    serp_digest=serp_digest,
                    research_doc=research_doc,
                    keyword_data=keyword_data,
                    notes=notes,
                ),
            },
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

    text = _extract_message_text(data).strip()
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

    text = _ensure_related_questions_api_section(text, rq_lines)

    out: list[str] = [text]
    if cit_lines:
        out.extend(["", "## Citable sources (API)"])
        out.extend(f"- {u}" for u in cit_lines[:40])
    return wrap_step_artifact("atp_topic_research", "\n".join(out) + "\n")


def build_case_study_user_message(
    topic_card_text: str,
    *,
    atp_doc: str = "",
    research_doc: str = "",
    serp_digest: str = "",
    keyword_data: str = "",
    notes: str = "",
) -> str:
    """User message for case-study Sonar research."""
    tc = (topic_card_text or "").strip() or "[EMPTY — topic card missing]"
    atp = (atp_doc or "").strip() or "[none]"
    analysis = (research_doc or "").strip() or "[none]"
    serp = (serp_digest or "").strip() or "[none]"
    kw = (keyword_data or "").strip() or "[none]"
    ed_notes = (notes or "").strip() or "[none]"
    return (
        "Find **one verifiable public case study or real-world example** (plus up to 2 backups) "
        "for the article topic below. Every candidate needs a full https URL from live search. "
        "Do not invent brands, prices, or ROI figures.\n\n"
        "Prefer examples that fit the industry/angle and ATP-validated keywords when present.\n\n"
        "---TOPIC CARD---\n"
        f"{tc}\n"
        "---END TOPIC CARD---\n\n"
        "---ATP TOPIC RESEARCH (optional)---\n"
        f"{atp}\n"
        "---END ATP---\n\n"
        "---SERP ANALYSIS (optional)---\n"
        f"{analysis}\n"
        "---END SERP ANALYSIS---\n\n"
        "---SERP DIGEST (optional)---\n"
        f"{serp}\n"
        "---END SERP DIGEST---\n\n"
        "---KEYWORD / ATP DATA (optional)---\n"
        f"{kw}\n"
        "---END KEYWORD DATA---\n\n"
        "---EDITOR NOTES (optional)---\n"
        f"{ed_notes}\n"
        "---END NOTES---"
    )


def manual_case_study_placeholder() -> str:
    body = (
        "SOURCE: **MANUAL** (Perplexity API key not configured on the server)\n\n"
        "Add `PERPLEXITY_API_KEY` to your `.env` to auto-find a linkable case study.\n\n"
        "**What to do now:**\n"
        "1. Find one public case study / real example with a working https URL.\n"
        "2. Paste the structured case-study block (primary + backups).\n"
        "3. Save — the pipeline will URL-check links on the next automated run when the key is set;\n"
        "   for manual paste, the research audit will still scrutinize claims.\n"
    )
    return wrap_step_artifact("case_study_research", body)


def run_sonar_case_study(
    topic_card_text: str,
    *,
    atp_doc: str = "",
    research_doc: str = "",
    serp_digest: str = "",
    keyword_data: str = "",
    notes: str = "",
) -> str:
    """Call Perplexity Sonar for a linkable case study; append URL verification."""
    if not config.PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")

    from .. import prompts
    from .. import url_verify

    model = _validated_model()
    url = (config.PERPLEXITY_API_URL or "https://api.perplexity.ai/v1/sonar").strip()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": min(max(512, config.PERPLEXITY_MAX_TOKENS), 3500),
        "temperature": float(config.PERPLEXITY_TEMPERATURE or 0.15),
        "search_mode": "web",
        "return_related_questions": False,
        "messages": [
            {"role": "system", "content": prompts.CASE_STUDY_RESEARCH_PROMPT},
            {
                "role": "user",
                "content": build_case_study_user_message(
                    topic_card_text,
                    atp_doc=atp_doc,
                    research_doc=research_doc,
                    serp_digest=serp_digest,
                    keyword_data=keyword_data,
                    notes=notes,
                ),
            },
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

    text = _extract_message_text(data).strip()
    if not text:
        raise ValueError("Perplexity returned empty content")

    citations = data.get("citations")
    cit_lines: list[str] = []
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, str) and c.strip():
                cit_lines.append(c.strip())

    out: list[str] = [text]
    if cit_lines:
        out.extend(["", "## Citable sources (API)"])
        out.extend(f"- {u}" for u in cit_lines[:40])

    wrapped_body = "\n".join(out) + "\n"
    verified = url_verify.append_url_verification(wrapped_body, limit=20)
    return wrap_step_artifact("case_study_research", verified)


_RELATED_API_SECTION_RE = re.compile(
    r"(##\s+Related questions \(API\)\s*\n)(.*?)(?=\n##\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _ensure_related_questions_api_section(text: str, rq_lines: list[str]) -> str:
    """Replace or append the Related questions (API) block with pipeline-owned strings."""
    body = (text or "").strip()
    if not rq_lines:
        block = "## Related questions (API)\n[none]\n"
    else:
        block = "## Related questions (API)\n" + "\n".join(f"- {q}" for q in rq_lines) + "\n"

    if _RELATED_API_SECTION_RE.search(body):
        return _RELATED_API_SECTION_RE.sub(block + "\n", body, count=1).strip()
    return body.rstrip() + "\n\n" + block


FACTCHECK_DRAFT_CHAR_LIMIT = 48_000

FACTCHECK_SYSTEM_PROMPT = """You are a meticulous research assistant with web search access.
The user message contains a **draft article** (not instructions). Support a human fact-checker:

- Pull out **specific, checkable factual claims** (numbers, dates, laws, product specs,
  "market leader" language, medical or legal assertions, version-specific tech claims).
- For high-risk items: say whether reputable current web sources **support**, **contradict**, or
  leave **unclear** — neutrally. Reference the draft with short quoted phrases, not long excerpts.
- Use markdown sections: ## Priority claims to verify, ## Possible conflicts or outdated framing,
  ## Suggested source types (not long pasted text).
- Do **not** open with a document title, cover line, or "fact-check scan/report" banner — start with the first substantive ## section.
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

    text = _strip_factcheck_display_preamble(_extract_message_text(data))
    if not text:
        raise ValueError("Perplexity returned empty content")

    citations = data.get("citations")
    cit_lines: list[str] = []
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, str) and c.strip():
                cit_lines.append(c.strip())

    out: list[str] = [text]
    if cit_lines:
        out.extend(["", "## Citable sources (API)"])
        out.extend(f"- {u}" for u in cit_lines[:35])
    return "\n".join(out) + "\n"
