import logging

from . import artifacts
from . import config
from . import editorial_input
from . import prompts
from .context_extractor import extract_for_step_5, extract_for_step_7
from . import faq_schema
from . import final_output_enforce
from . import writing_format_enforce
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)

_PIPELINE_STEP_NUM: dict[str, int] = {
    # Must match `backend/pipeline.py` STEP_ORDER.
    "topic_card": 1,
    "serp_research": 2,
    "research": 3,
    "assignment_brief": 4,
    "outline": 5,
    "draft": 6,
    "fact_check": 7,
    "final_output": 8,
}


def _step_num(step_name: str) -> int | None:
    return _PIPELINE_STEP_NUM.get(step_name)


def _step_label(step_name: str) -> str:
    n = _step_num(step_name)
    if n is None:
        return f"Step ? ({step_name})"
    return f"Step {n} ({step_name})"


def _debug_log_system_prompt(step_label: str, system_msg: str) -> None:
    logger.debug(
        "%s system_len=%s has_context_md=%s preview=%s",
        step_label,
        len(system_msg),
        "context.md" in system_msg,
        system_msg[:300].replace("\n", " "),
    )


def _load_prior_artifact(client_id: str, run_id: str, step_name: str) -> str:
    try:
        return artifacts.load_artifact(client_id, run_id, step_name)
    except FileNotFoundError:
        return ""


def _chat_complete(
    system_msg: str,
    user_msg: str,
    step_label: str,
    *,
    debug_system_message: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    if debug_system_message:
        _debug_log_system_prompt(step_label, system_msg)
    return claude.chat_complete(
        system_msg,
        user_msg,
        step_label=step_label,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _word_count_target_for_run(client_id: str, run_id: str) -> int | None:
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    return editorial_input.word_count_target_from_manifest(manifest)


def _faq_notice_for_run(client_id: str, run_id: str) -> str:
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    if isinstance(manual, dict) and editorial_input.should_include_faq(manual):
        return editorial_input.faq_editorial_notice()
    return ""


def _external_links_notice_for_run(client_id: str, run_id: str) -> str:
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    if isinstance(manual, dict) and editorial_input.should_include_external_links(
        manual
    ):
        return editorial_input.external_links_editorial_notice()
    return ""


def _editorial_notices_for_run(client_id: str, run_id: str) -> str:
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    notes = (
        editorial_input.notes_editorial_notice(manual)
        if isinstance(manual, dict)
        else ""
    )
    return (
        notes
        + editorial_input.seo_readability_notice()
        + editorial_input.writing_format_guidelines_notice()
        + _faq_notice_for_run(client_id, run_id)
        + _external_links_notice_for_run(client_id, run_id)
    )


def _with_word_count_system(system_msg: str, target: int | None) -> str:
    if not target:
        return system_msg
    return editorial_input.system_word_count_override(target) + system_msg


def _with_word_count_user(user_msg: str, target: int | None) -> str:
    if not target:
        return user_msg
    block = editorial_input.user_word_count_block(target)
    if block.strip() in user_msg:
        return user_msg
    return block + user_msg


def _draft_max_tokens(target: int | None) -> int | None:
    if not target:
        return None
    # Long articles need a large output budget (~2 tokens/word + structure).
    return min(8192, max(6000, int(target * 2.2) + 1200))


def _trim_draft_word_count(
    draft: str,
    target: int,
    *,
    system_msg: str,
) -> str:
    """Trim an over-long draft to the form target window."""
    low, high = editorial_input.word_count_bounds(target)
    text = (draft or "").strip()
    current = editorial_input.count_article_words(text)
    if current <= high:
        return text
    trim_user = (
        f"The draft below is TOO LONG and must be shortened.\n"
        f"- Current word count: {current:,}\n"
        f"- Editor form target: {target:,} words\n"
        f"- Acceptable range: {low:,}–{high:,} words (hard maximum {high:,})\n\n"
        f"Rules:\n"
        f"- Keep the same H1 and H2 section headings (you may shorten section prose).\n"
        f"- Preserve the FAQ section (it does not count toward the word target) and inline "
        f"links: external [2–3 words](https://…) and internal [2–3 words](INTERNAL: cluster) "
        f"if present.\n"
        f"- Count only body prose toward the {high:,}-word maximum (exclude FAQ headings/answers).\n"
        f"- Remove redundancy, repeated examples, and filler — not entire sections.\n"
        f"- Output ONLY the full trimmed article in markdown.\n\n"
        f"---DRAFT TO TRIM---\n{text}\n"
    )
    logger.info(
        "draft trim: %s words -> target %s (max %s)",
        current,
        target,
        high,
    )
    return _chat_complete(
        system_msg,
        trim_user,
        f"Step {_step_num('draft') or '?'} (draft trim)",
        max_tokens=_draft_max_tokens(target),
        temperature=0.4,
    ).strip()


def _ensure_draft_word_count(
    draft: str,
    target: int,
    *,
    system_msg: str,
    outline: str,
    max_rounds: int = 3,
) -> str:
    """Expand or trim draft until it sits within the form word-count window."""
    low, high = editorial_input.word_count_bounds(target)
    text = (draft or "").strip()
    current = editorial_input.count_article_words(text)
    if low <= current <= high:
        return text
    if current > high:
        for _ in range(2):
            text = _trim_draft_word_count(text, target, system_msg=system_msg)
            current = editorial_input.count_article_words(text)
            if current <= high:
                break
        if low <= current <= high:
            return text

    outline_excerpt = (outline or "").strip()[:12000]
    for round_i in range(max_rounds):
        if current >= low:
            break
        shortage = max(50, target - current)
        expand_user = (
            f"The draft below is TOO SHORT and must be expanded.\n"
            f"- Current word count: {current:,}\n"
            f"- Editor form target: {target:,} words\n"
            f"- Acceptable minimum: {low:,} words (maximum ~{high:,})\n"
            f"- Add approximately {shortage:,} more words of substantive prose.\n\n"
            f"Rules:\n"
            f"- Keep the same H1/H2 structure and markdown format.\n"
            f"- Expand every major section with examples, steps, and detail.\n"
            f"- Do not add filler, repetition, or meta-commentary.\n"
            f"- Output ONLY the full expanded article in markdown.\n\n"
            f"---OUTLINE (structure reference)---\n{outline_excerpt}\n\n"
            f"---DRAFT TO EXPAND---\n{text}\n"
        )
        logger.info(
            "draft expansion round %s: %s words -> target %s (min %s)",
            round_i + 1,
            current,
            target,
            low,
        )
        text = _chat_complete(
            system_msg,
            expand_user,
            f"Step {_step_num('draft') or '?'} (draft expansion {round_i + 1})",
            max_tokens=_draft_max_tokens(target),
            temperature=0.5,
        )
        current = editorial_input.count_article_words(text)

    if current < low:
        logger.warning(
            "draft still short after %s expansions: %s words (target %s, min %s)",
            max_rounds,
            current,
            target,
            low,
        )
    return text


def run_step_1(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "topic_card"
    context = artifacts.load_context(client_id, step_name)
    wc_target = _word_count_target_for_run(client_id, run_id)
    system_msg = _with_word_count_system(
        prompts.TOPIC_CARD_PROMPT + "\n" + context, wc_target
    )
    step_label = _step_label(step_name)

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    built = (
        editorial_input.build_topic_payload(manual)
        if isinstance(manual, dict)
        else ""
    )
    user_msg = (built or previous_artifact or "").strip()
    if isinstance(manual, dict):
        user_msg += editorial_input.notes_editorial_notice(manual)
    user_msg += editorial_input.seo_readability_notice()
    if wc_target:
        user_msg += editorial_input.mandatory_word_count_notice(wc_target)

    output = _chat_complete(
        system_msg,
        user_msg,
        step_label,
        debug_system_message=True,
    )
    if wc_target:
        output = editorial_input.enforce_word_count_in_topic_card(output, wc_target)
    if isinstance(manual, dict):
        output = editorial_input.apply_manual_keywords_topic_card(
            output, manual, semrush_notes=""
        )
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_serp_research(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Step 2 — Perplexity Sonar (or manual placeholder when API key unset)."""
    step_name = "serp_research"
    from .integrations import perplexity as ppx

    if config.PERPLEXITY_API_KEY:
        try:
            output = ppx.run_sonar_serp(previous_artifact)
        except Exception as e:
            logger.exception("Perplexity SERP step failed")
            raise RuntimeError(f"Perplexity SERP failed: {e}") from e
    else:
        logger.info("%s: no PERPLEXITY_API_KEY — writing manual placeholder", step_name)
        output = ppx.manual_serp_placeholder()

    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_2(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "assignment_brief"
    context = artifacts.load_context(client_id, step_name)
    wc_target = _word_count_target_for_run(client_id, run_id)
    system_msg = _with_word_count_system(
        prompts.with_writing_format_guidelines(prompts.ASSIGNMENT_BRIEF_PROMPT)
        + "\n"
        + context,
        wc_target,
    )
    step_label = _step_label(step_name)
    topic_card = _load_prior_artifact(client_id, run_id, "topic_card")
    tc_step = _step_num("topic_card") or "?"
    research_step = _step_num("research") or "?"
    user_msg = (
        f"---TOPIC CARD (STEP {tc_step})---\n"
        f"{topic_card.strip() or f'[TOPIC CARD ARTIFACT MISSING — re-run Step {tc_step}]'}\n\n"
        f"---SERP ANALYSIS & GAPS (STEP {research_step})---\n"
        f"{previous_artifact.strip()}\n"
    )
    user_msg += _editorial_notices_for_run(client_id, run_id)
    if wc_target:
        user_msg += editorial_input.mandatory_word_count_notice(wc_target)
    user_msg = _with_word_count_user(user_msg, wc_target)
    output = _chat_complete(
        system_msg,
        user_msg,
        step_label,
        debug_system_message=True,
    )
    if wc_target:
        output = editorial_input.enforce_word_count_in_brief(output, wc_target)
    output = writing_format_enforce.enforce_brief(output, allow_llm_repair=True)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_3(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "research"
    context = artifacts.load_context(client_id, step_name)
    system_msg = prompts.RESEARCH_PROMPT + "\n" + context
    step_label = _step_label(step_name)
    topic_card = _load_prior_artifact(client_id, run_id, "topic_card")
    tc_step = _step_num("topic_card") or "?"
    serp_step = _step_num("serp_research") or "?"
    user_msg = (
        f"---TOPIC CARD (STEP {tc_step})---\n"
        f"{topic_card.strip() or f'[TOPIC CARD ARTIFACT MISSING — re-run Step {tc_step}]'}\n\n"
        f"---SERP RESEARCH DIGEST (STEP {serp_step})---\n"
        f"{previous_artifact.strip()}\n"
    )
    output = _chat_complete(system_msg, user_msg, step_label)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_4(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "outline"
    context = artifacts.load_context(client_id, step_name)
    wc_target = _word_count_target_for_run(client_id, run_id)
    system_msg = _with_word_count_system(
        prompts.with_writing_format_guidelines(prompts.OUTLINE_PROMPT) + "\n" + context,
        wc_target,
    )
    step_label = _step_label(step_name)
    research_doc = _load_prior_artifact(client_id, run_id, "research")
    brief_step = _step_num("assignment_brief") or "?"
    research_step = _step_num("research") or "?"
    user_msg = (
        f"---ASSIGNMENT BRIEF (STEP {brief_step})---\n"
        f"{previous_artifact.strip()}\n\n"
        f"---SERP ANALYSIS & RESEARCH (STEP {research_step})---\n"
        f"{research_doc.strip() or f'[STEP {research_step} ARTIFACT MISSING — re-run SERP analysis]'}\n"
    )
    user_msg += _editorial_notices_for_run(client_id, run_id)
    user_msg += editorial_input.outline_format_guidelines_notice()
    if wc_target:
        user_msg += editorial_input.mandatory_word_count_notice(wc_target)
    user_msg = _with_word_count_user(user_msg, wc_target)
    output = _chat_complete(system_msg, user_msg, step_label)
    if wc_target:
        output = editorial_input.enforce_outline_section_word_counts(output, wc_target)
    output = writing_format_enforce.enforce_outline(output, allow_llm_repair=True)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_5(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "draft"
    context = artifacts.load_context(client_id, step_name)
    extracted = extract_for_step_5(client_id)

    va_lines: list[str] = []
    for item in extracted.get("voice_attributes") or []:
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
    voice_attrs_block = (
        "\n".join(va_lines) if va_lines else "None specified"
    )

    bt = extracted.get("blog_tone")
    blog_tone_line = (
        f"BLOG POST TONE (for blog articles): {bt.get('tone', '')}\n"
        if isinstance(bt, dict) and bt.get("tone")
        else ""
    )

    brand_voice_section = f"""
---BRAND VOICE RULES FOR {extracted['company_name'].upper()}---
CRITICAL: You MUST follow these rules. Do not deviate.
{blog_tone_line}BANNED WORDS (do not use any of these):
{', '.join(extracted['banned_words']) if extracted.get('banned_words') else 'None specified'}
VOICE ATTRIBUTES (write with these — each line may include Right/Wrong examples):
{voice_attrs_block}
TARGET PERSONAS (write for these people):
{', '.join(extracted['persona_names']) if extracted.get('persona_names') else 'Unknown'}
VOCABULARY PREFERENCES:
Instead of generic corporate language, use:
{chr(10).join([f'  Instead of "{dnt}": use "{dw}"' for dnt, dw in zip(extracted.get('do_not_write_like') or [], extracted.get('do_write_like') or [])]) if extracted.get('do_not_write_like') else 'None specified'}
---END BRAND VOICE RULES---
"""
    wc_target = _word_count_target_for_run(client_id, run_id)
    system_msg = _with_word_count_system(
        prompts.with_writing_format_guidelines(prompts.DRAFT_PROMPT)
        + "\n\n"
        + brand_voice_section
        + "\n\n"
        + context,
        wc_target,
    )
    step_label = _step_label(step_name)
    research_doc = _load_prior_artifact(client_id, run_id, "research")
    outline_step = _step_num("outline") or "?"
    research_step = _step_num("research") or "?"
    user_msg = (
        f"---ARTICLE OUTLINE (STEP {outline_step})---\n"
        f"{previous_artifact.strip()}\n\n"
        f"---SERP ANALYSIS & RESEARCH (STEP {research_step})---\n"
        f"{research_doc.strip() or f'[STEP {research_step} ARTIFACT MISSING — re-run SERP analysis]'}\n"
    )
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    user_msg += (
        "\n\n---SERP RESEARCH DIGEST (use for external source URLs)---\n"
        f"{serp_digest.strip() or '[No SERP digest — cite only URLs you can justify from research]'}\n"
    )
    user_msg += _editorial_notices_for_run(client_id, run_id)
    if wc_target:
        user_msg += editorial_input.mandatory_word_count_notice(wc_target)
        user_msg += editorial_input.draft_word_count_requirement(wc_target)
    user_msg = _with_word_count_user(user_msg, wc_target)
    output = _chat_complete(
        system_msg,
        user_msg,
        step_label,
        debug_system_message=True,
        max_tokens=_draft_max_tokens(wc_target),
        temperature=0.55,
    )
    if wc_target:
        output = _ensure_draft_word_count(
            output,
            wc_target,
            system_msg=system_msg,
            outline=previous_artifact,
        )
        words = editorial_input.count_article_words(output)
        logger.info(
            "draft word count %s (target %s)",
            words,
            wc_target,
        )
    output = writing_format_enforce.enforce_article(
        output, stage="draft", allow_llm_repair=True
    )
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_6(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "fact_check"
    context = artifacts.load_context(client_id, step_name)
    system_msg = prompts.FACT_CHECK_PROMPT + "\n" + context
    step_label = _step_label(step_name)

    draft = (previous_artifact or "").strip()
    draft_step = _step_num("draft") or "?"
    ppx_block = ""
    if config.PERPLEXITY_API_KEY:
        try:
            from .integrations import perplexity as ppx

            ppx_block = ppx.run_sonar_draft_factcheck(draft)
        except Exception as e:
            logger.exception("Perplexity draft fact-check failed")
            ppx_block = (
                f"[Perplexity draft fact-check FAILED — editor may run manual check. "
                f"Detail: {e}]"
            )
    else:
        ppx_block = (
            "[Perplexity web fact-check skipped — set PERPLEXITY_API_KEY in `.env` "
            "to run an automatic web scan before the editor fact-check.]"
        )

    user_msg = (
        f"---ARTICLE DRAFT (PIPELINE STEP {draft_step})---\n"
        f"{draft}\n\n"
        "---PERPLEXITY WEB FACT-CHECK (raw signals — verify independently)---\n"
        f"{ppx_block}\n"
    )
    claude_out = _chat_complete(system_msg, user_msg, step_label)
    combined = (
        "---PERPLEXITY WEB FACT-CHECK (raw audit trail)---\n"
        + ppx_block.strip()
        + "\n\n---EDITOR FACT-CHECK (Claude — publishable block follows)---\n"
        + claude_out.strip()
        + "\n"
    )
    artifacts.save_artifact(client_id, run_id, step_name, combined)
    logger.info("step complete %s", step_name)
    return combined


def run_step_7(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "final_output"
    context = artifacts.load_context(client_id, step_name)
    extracted = extract_for_step_7(client_id)

    cluster_section = f"""
---INTERNAL LINKING GUIDE---
These are the content clusters for this client:
{chr(10).join([f'{i+1}. {cluster}' for i, cluster in enumerate(extracted['clusters'])]) if extracted['clusters'] else 'No clusters defined'}
When linking, reference only these cluster names.
CTA Philosophy: {extracted['cta_philosophy']}
---END LINKING GUIDE---
"""
    wc_target = _word_count_target_for_run(client_id, run_id)
    system_msg = _with_word_count_system(
        prompts.with_writing_format_guidelines(prompts.FINAL_OUTPUT_PROMPT)
        + "\n\n"
        + cluster_section
        + "\n\n"
        + context,
        wc_target,
    )
    step_label = _step_label(step_name)
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    research_doc = _load_prior_artifact(client_id, run_id, "research")
    serp_step = _step_num("serp_research") or "?"
    research_step = _step_num("research") or "?"
    user_msg = (
        f"{previous_artifact.strip()}\n\n"
        "---SOURCES FOR EXTERNAL LINKS (URLs must appear here — do not invent)---\n"
        f"---SERP RESEARCH (STEP {serp_step})---\n{serp_digest.strip()}\n\n"
        f"---SERP ANALYSIS (STEP {research_step})---\n{research_doc.strip()}\n"
        "---END SOURCES---\n"
    )
    user_msg += _editorial_notices_for_run(client_id, run_id)
    user_msg += editorial_input.cta_format_guidelines_notice()
    if wc_target:
        user_msg += editorial_input.mandatory_word_count_notice(wc_target)
        user_msg += editorial_input.draft_word_count_requirement(wc_target)
    user_msg = _with_word_count_user(user_msg, wc_target)
    output = _chat_complete(
        system_msg,
        user_msg,
        step_label,
        max_tokens=_draft_max_tokens(wc_target),
    )
    output = final_output_enforce.enforce_final_output(
        output, client_id, run_id, allow_llm_repair=True
    )
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output
