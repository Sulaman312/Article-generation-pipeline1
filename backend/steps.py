import logging

from . import artifacts
from . import config
from . import editorial_input
from . import prompts
from .context_extractor import extract_for_step_5, extract_for_step_7
from . import faq_schema
from . import final_output_enforce
from .step_markers import wrap_step_artifact
from . import writing_format_enforce
from .integrations import anthropic as claude
from .pipeline_steps import ARTICLE_STEP_ORDER

logger = logging.getLogger(__name__)

_PIPELINE_STEP_NUM: dict[str, int] = {
    name: index for index, name in enumerate(ARTICLE_STEP_ORDER, start=1)
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
        return editorial_input.faq_editorial_notice(manual)
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


def _trim_article_by_sections(
    article: str,
    target: int,
    *,
    system_msg: str,
    outline: str = "",
    step_label: str = "section trim",
    max_passes: int = 3,
) -> str:
    from . import word_count_enforce

    return word_count_enforce.trim_article_by_sections(
        article,
        target,
        system_msg=system_msg,
        outline=outline,
        step_label=step_label,
        max_passes=max_passes,
    )


def _ensure_draft_word_count(
    draft: str,
    target: int,
    *,
    system_msg: str,
    outline: str,
    max_rounds: int = 3,
) -> str:
    """Expand or section-trim draft until it sits within the form word-count window."""
    low, high = editorial_input.word_count_bounds(target)
    text = (draft or "").strip()
    current = editorial_input.count_article_words(text)
    if low <= current <= high:
        return text
    if current > high:
        text = _trim_article_by_sections(
            text,
            target,
            system_msg=system_msg,
            outline=outline,
            step_label=f"Step {_step_num('draft') or '?'} (section trim)",
        )
        current = editorial_input.count_article_words(text)
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
            f"- Stay under {high:,} body words after expansion.\n"
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
        if current > high:
            text = _trim_article_by_sections(
                text,
                target,
                system_msg=system_msg,
                outline=outline,
                step_label=f"Step {_step_num('draft') or '?'} (post-expand trim)",
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
    elif current > high:
        logger.warning(
            "draft still long after section trim: %s words (target %s, max %s)",
            current,
            target,
            high,
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
    output = wrap_step_artifact(step_name, output)
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

    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_source_research(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """One UI step: ATP + PAA/FAQ + case study (Perplexity) + Claude research audit.

    Still writes the individual artifacts so brief/outline/draft/hard-gates keep working.
    """
    step_name = "source_research"
    research_doc = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "research"
    )

    atp = run_atp_topic_research(client_id, run_id, research_doc)
    paa = run_paa_faq_research(client_id, run_id, atp)
    case = run_case_study_research(client_id, run_id, paa)
    audit = run_research_audit(client_id, run_id, case)

    from .step_markers import extract_step_body

    audit_body = extract_step_body("research_audit", audit) or audit
    combined = (
        "This pack combines AnswerThePublic-style topic research, PAA/FAQ research, "
        "case-study research (URL-checked), and a Claude research audit.\n\n"
        "Use the **Research Audit** section as the mandatory gate for brief → draft. "
        "Full ATP / PAA / case-study artifacts are also saved on this run for reference.\n\n"
        "## Research audit (approved for drafting)\n\n"
        f"{audit_body.strip()}\n"
    )
    output = wrap_step_artifact(step_name, combined)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_atp_topic_research(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """AnswerThePublic-style topic research — Perplexity Sonar (or manual placeholder)."""
    step_name = "atp_topic_research"
    from .integrations import perplexity as ppx

    topic_card = _load_prior_artifact(client_id, run_id, "topic_card")
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    research_doc = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "research"
    )
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    notes = ""
    keyword_data = ""
    if isinstance(manual, dict):
        notes = editorial_input.notes_from_manual(manual)
        keyword_data = _keyword_data_from_manual(manual if isinstance(manual, dict) else None)

    if config.PERPLEXITY_API_KEY:
        try:
            output = ppx.run_sonar_atp_topic(
                topic_card,
                serp_digest=serp_digest,
                research_doc=research_doc,
                keyword_data=keyword_data,
                notes=notes,
            )
        except Exception as e:
            logger.exception("Perplexity ATP topic research failed")
            raise RuntimeError(f"Perplexity ATP topic research failed: {e}") from e
    else:
        logger.info("%s: no PERPLEXITY_API_KEY — writing manual placeholder", step_name)
        output = ppx.manual_atp_topic_placeholder()

    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def _atp_block_for_run(client_id: str, run_id: str) -> str:
    """Inject ATP topic research into brief/outline/draft user messages."""
    atp = _load_prior_artifact(client_id, run_id, "atp_topic_research")
    src_step = _step_num("source_research") or "?"
    if not atp.strip():
        return (
            f"\n\n---ATP TOPIC RESEARCH (from Source Research step {src_step})---\n"
            f"[MISSING — re-run Source Research (step {src_step}). Until then, do not invent "
            "a full supporting cluster; use only clearly needed long-tails.]\n"
        )
    return (
        f"\n\n---ATP TOPIC RESEARCH (from Source Research step {src_step}) — "
        "KEYWORDS + SUPPORTING CLUSTER---\n"
        f"{atp.strip()}\n"
        "Use high-intent phrases and main-article long-tails naturally (at most once each). "
        "Plan or place INTERNAL links toward supporting posts using "
        "`[short anchor](INTERNAL: Supporting: <title>)`. "
        "Respect LOW SIGNAL — do not invent extra cluster posts.\n"
    )


def _keyword_data_from_manual(manual: dict | None) -> str:
    if not isinstance(manual, dict):
        return ""
    return (
        manual.get("Keyword Data")
        or manual.get("keyword_data")
        or manual.get("ATP Data")
        or manual.get("atp_data")
        or manual.get("AnswerThePublic")
        or ""
    ).strip()


def run_case_study_research(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Find a linkable case study via Perplexity; pipeline URL-checks citations."""
    step_name = "case_study_research"
    from .integrations import perplexity as ppx
    from . import url_verify

    topic_card = _load_prior_artifact(client_id, run_id, "topic_card")
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    research_doc = _load_prior_artifact(client_id, run_id, "research")
    atp_doc = _load_prior_artifact(client_id, run_id, "atp_topic_research")
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    notes = editorial_input.notes_from_manual(manual) if isinstance(manual, dict) else ""
    keyword_data = _keyword_data_from_manual(manual if isinstance(manual, dict) else None)

    if config.PERPLEXITY_API_KEY:
        try:
            output = ppx.run_sonar_case_study(
                topic_card,
                atp_doc=atp_doc,
                research_doc=research_doc,
                serp_digest=serp_digest,
                keyword_data=keyword_data,
                notes=notes,
            )
        except Exception as e:
            logger.exception("Perplexity case study research failed")
            raise RuntimeError(f"Perplexity case study research failed: {e}") from e
    else:
        logger.info("%s: no PERPLEXITY_API_KEY — writing manual placeholder", step_name)
        output = ppx.manual_case_study_placeholder()
        # Still URL-check any links the editor may have pasted on re-run.
        if "https://" in output.lower():
            output = wrap_step_artifact(
                step_name, url_verify.append_url_verification(output, limit=20)
            )

    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_research_audit(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Claude gate: scrub Perplexity artifacts before brief/draft."""
    step_name = "research_audit"
    context = artifacts.load_context(client_id, step_name)
    system_msg = prompts.RESEARCH_AUDIT_PROMPT + "\n" + context
    step_label = _step_label(step_name)

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    notes = editorial_input.notes_from_manual(manual) if isinstance(manual, dict) else ""
    keyword_data = _keyword_data_from_manual(manual if isinstance(manual, dict) else None)

    case_study = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "case_study_research"
    )
    user_msg = (
        "Audit the following research artifacts. Reject fabricated brands, prices, stats, "
        "and dead/FAIL URLs. Approve only what draft/brief may use.\n\n"
        f"---SERP RESEARCH DIGEST---\n"
        f"{_load_prior_artifact(client_id, run_id, 'serp_research').strip() or '[none]'}\n\n"
        f"---SERP ANALYSIS---\n"
        f"{_load_prior_artifact(client_id, run_id, 'research').strip() or '[none]'}\n\n"
        f"---ATP TOPIC RESEARCH---\n"
        f"{_load_prior_artifact(client_id, run_id, 'atp_topic_research').strip() or '[none]'}\n\n"
        f"---PAA / FAQ RESEARCH---\n"
        f"{_load_prior_artifact(client_id, run_id, 'paa_faq_research').strip() or '[none]'}\n\n"
        f"---CASE STUDY RESEARCH (includes URL verification)---\n"
        f"{case_study.strip() or '[none]'}\n\n"
        f"---KEYWORD / ATP PASTE (optional)---\n"
        f"{keyword_data or '[none]'}\n\n"
        f"---EDITOR NOTES---\n"
        f"{notes or '[none]'}\n"
    )
    output = _chat_complete(
        system_msg,
        user_msg,
        step_label,
        temperature=0.2,
        max_tokens=3500,
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def _research_audit_block_for_run(client_id: str, run_id: str) -> str:
    audit = _load_prior_artifact(client_id, run_id, "research_audit")
    src_step = _step_num("source_research") or "?"
    if not audit.strip():
        return (
            f"\n\n---RESEARCH AUDIT (from Source Research step {src_step})---\n"
            f"[MISSING — re-run Source Research (step {src_step}) before drafting. "
            "Do not invent case studies, stats, or FAQ banks.]\n"
        )
    return (
        f"\n\n---RESEARCH AUDIT (from Source Research step {src_step}) — MANDATORY GATE---\n"
        f"{audit.strip()}\n"
        "Follow APPROVED sections only. Never use FLAGGED / reject-list claims. "
        "If STATUS is NO APPROVED CASE STUDY, do not invent one. "
        "Use approved FAQ questions and supporting cluster titles only.\n"
    )


def run_supporting_posts(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Claude drafts supporting blog posts from the audited ATP cluster."""
    step_name = "supporting_posts"
    context = artifacts.load_context(client_id, step_name)
    system_msg = (
        prompts.with_writing_format_guidelines(prompts.SUPPORTING_POSTS_PROMPT)
        + "\n"
        + context
    )
    step_label = _step_label(step_name)

    draft = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "draft"
    )
    outline = _load_prior_artifact(client_id, run_id, "outline")
    user_msg = (
        f"{_research_audit_block_for_run(client_id, run_id)}"
        f"{_atp_block_for_run(client_id, run_id)}"
        f"---MAIN ARTICLE DRAFT---\n"
        f"{draft.strip() or '[draft missing — use outline titles for interlinks]'}\n\n"
        f"---MAIN ARTICLE OUTLINE---\n"
        f"{outline.strip() or '[none]'}\n"
    )
    user_msg += _editorial_notices_for_run(client_id, run_id)
    output = _chat_complete(
        system_msg,
        user_msg,
        step_label,
        temperature=0.55,
        max_tokens=8000,
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_paa_faq_research(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """PAA / FAQ research — Perplexity Sonar question bank (or manual placeholder)."""
    step_name = "paa_faq_research"
    from .integrations import perplexity as ppx

    topic_card = _load_prior_artifact(client_id, run_id, "topic_card")
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    research_doc = _load_prior_artifact(client_id, run_id, "research")
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    notes = ""
    keyword_data = ""
    if isinstance(manual, dict):
        notes = editorial_input.notes_from_manual(manual)
        keyword_data = _keyword_data_from_manual(manual if isinstance(manual, dict) else None)
    atp_prior = _load_prior_artifact(client_id, run_id, "atp_topic_research")
    if atp_prior.strip():
        from . import atp_research

        bank = atp_research.format_atp_bank_for_prompt(atp_prior)
        if bank:
            keyword_data = (
                f"{keyword_data}\n\n---FROM ATP TOPIC RESEARCH---\n{bank}".strip()
                if keyword_data
                else f"---FROM ATP TOPIC RESEARCH---\n{bank}"
            )

    if config.PERPLEXITY_API_KEY:
        try:
            output = ppx.run_sonar_paa_faq(
                topic_card,
                serp_digest=serp_digest,
                research_doc=research_doc,
                keyword_data=keyword_data,
                notes=notes,
            )
        except Exception as e:
            logger.exception("Perplexity PAA FAQ step failed")
            raise RuntimeError(f"Perplexity PAA FAQ failed: {e}") from e
    else:
        logger.info("%s: no PERPLEXITY_API_KEY — writing manual placeholder", step_name)
        output = ppx.manual_paa_faq_placeholder()

    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def _paa_faq_block_for_run(client_id: str, run_id: str) -> str:
    """Inject the PAA FAQ research artifact into brief/outline/draft user messages."""
    paa = _load_prior_artifact(client_id, run_id, "paa_faq_research")
    src_step = _step_num("source_research") or "?"
    if not paa.strip():
        return (
            f"\n\n---PAA / FAQ RESEARCH (from Source Research step {src_step})---\n"
            f"[MISSING — re-run Source Research (step {src_step}). Until then, do not invent "
            "a full FAQ bank; use only clearly needed questions and mark uncertainty.]\n"
        )
    return (
        f"\n\n---PAA / FAQ RESEARCH (from Source Research step {src_step}) — "
        "MANDATORY FAQ SOURCE---\n"
        f"{paa.strip()}\n"
        "Use the **Recommended FAQ bank** questions for the article FAQ. "
        "Do not invent a parallel FAQ set in another language. "
        "Respect LOW SIGNAL / KEYWORD DATA SHOWS LOW/NO DEMAND flags — do not pad to 6–8.\n"
    )


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
    research_doc = _load_prior_artifact(client_id, run_id, "research")
    user_msg = (
        f"---TOPIC CARD (STEP {tc_step})---\n"
        f"{topic_card.strip() or f'[TOPIC CARD ARTIFACT MISSING — re-run Step {tc_step}]'}\n\n"
        f"---SERP ANALYSIS & GAPS (STEP {research_step})---\n"
        f"{research_doc.strip() or f'[STEP {research_step} ARTIFACT MISSING — re-run SERP analysis]'}\n"
        f"{_research_audit_block_for_run(client_id, run_id)}"
        f"{_atp_block_for_run(client_id, run_id)}"
        f"{_paa_faq_block_for_run(client_id, run_id)}"
        "Prefer **Research Audit → Approved FAQ questions** when present; otherwise use the "
        "Source Research FAQ bank. Do not invent a parallel FAQ set. "
        "Respect LOW SIGNAL / low-demand flags.\n"
        "Prefer **Research Audit → Approved case study** for E-E-A-T proof — never invent one.\n"
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
    output = wrap_step_artifact(step_name, output)
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
    output = wrap_step_artifact(step_name, output)
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
        f"{_research_audit_block_for_run(client_id, run_id)}"
        f"{_atp_block_for_run(client_id, run_id)}"
        f"{_paa_faq_block_for_run(client_id, run_id)}"
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
    output = wrap_step_artifact(step_name, output)
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
        f"{_research_audit_block_for_run(client_id, run_id)}"
        f"{_atp_block_for_run(client_id, run_id)}"
        f"{_paa_faq_block_for_run(client_id, run_id)}"
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
        user_msg += editorial_input.draft_section_budget_guidance(
            previous_artifact, wc_target
        )
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
            "draft word count after generation enforce %s (target %s)",
            words,
            wc_target,
        )
    output = writing_format_enforce.enforce_article(
        output, stage="draft", allow_llm_repair=True
    )
    # Format repair can inflate length — re-assert the generation window.
    if wc_target:
        low, high = editorial_input.word_count_bounds(wc_target)
        words = editorial_input.count_article_words(output)
        if words < low or words > high:
            output = _ensure_draft_word_count(
                output,
                wc_target,
                system_msg=system_msg,
                outline=previous_artifact,
            )
            words = editorial_input.count_article_words(output)
        logger.info("draft final word count %s (target %s)", words, wc_target)
    from . import hard_gates

    output = hard_gates.enforce_article_gates(
        output,
        client_id=client_id,
        run_id=run_id,
        stage="draft",
        allow_llm_repair=True,
        raise_on_fail=True,
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    # Supporting cluster drafts are generated as a sidecar (not a separate UI step).
    try:
        run_supporting_posts(client_id, run_id, output)
    except Exception:
        logger.exception(
            "supporting posts generation failed after draft (non-fatal for main article)"
        )
    return output


def run_step_6(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "fact_check"
    context = artifacts.load_context(client_id, step_name)
    system_msg = prompts.FACT_CHECK_PROMPT + "\n" + context
    step_label = _step_label(step_name)

    draft = _load_prior_artifact(client_id, run_id, "draft").strip() or (
        previous_artifact or ""
    ).strip()
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

    wc_target = _word_count_target_for_run(client_id, run_id)
    user_msg = (
        f"---ARTICLE DRAFT (PIPELINE STEP {draft_step})---\n"
        f"{draft}\n\n"
        "---PERPLEXITY WEB FACT-CHECK (raw signals — verify independently)---\n"
        f"{ppx_block}\n"
    )
    if wc_target:
        low, high = editorial_input.word_count_bounds(wc_target)
        draft_words = editorial_input.count_article_words(draft)
        user_msg += (
            f"\n\n=== LENGTH PRESERVATION (NON-NEGOTIABLE) ===\n"
            f"The draft body is already written to length "
            f"({draft_words:,} words; form target {wc_target:,}, band {low:,}–{high:,}).\n"
            f"In ---CORRECTED ARTICLE--- keep nearly the same body length. "
            f"Fix facts/clarity; do NOT expand into a longer rewrite. "
            f"FAQ may stay as-is (it does not count toward the band).\n"
        )
    claude_out = _chat_complete(system_msg, user_msg, step_label)
    # Keep corrected article inside the generation band when possible.
    if wc_target:
        corrected = faq_schema.extract_corrected_article_body(claude_out)
        if corrected:
            low, high = editorial_input.word_count_bounds(wc_target)
            words = editorial_input.count_article_words(corrected)
            if words > high:
                outline = _load_prior_artifact(client_id, run_id, "outline")
                trimmed = _trim_article_by_sections(
                    corrected,
                    wc_target,
                    system_msg=system_msg,
                    outline=outline,
                    step_label=f"Step {_step_num('fact_check') or '?'} (section trim)",
                )
                start = claude_out.find(faq_schema.CORRECTED_ARTICLE_START)
                end = claude_out.find(faq_schema.CORRECTED_ARTICLE_END)
                if start != -1 and end != -1 and end > start:
                    claude_out = (
                        claude_out[: start + len(faq_schema.CORRECTED_ARTICLE_START)]
                        + "\n"
                        + trimmed.strip()
                        + "\n"
                        + claude_out[end:]
                    )
    claude_out = wrap_step_artifact(step_name, claude_out)
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
    fact_check = _load_prior_artifact(client_id, run_id, "fact_check")
    user_msg = (
        f"{fact_check.strip() or '[fact_check artifact missing]'}\n\n"
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
        user_msg += (
            "\n=== FINAL OUTPUT LENGTH ===\n"
            "The corrected article was written to the form word band. "
            "Publish with nearly the same body length — do not expand. "
            "Use section budgets from the outline; FAQ stays extra (not counted).\n"
        )
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
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def _article_excerpt_for_meta(article_source: str, *, max_chars: int = 2500) -> str:
    from . import faq_schema

    body = (
        faq_schema.extract_corrected_article_body(article_source)
        or faq_schema.extract_final_article_body(article_source)
        or (article_source or "").strip()
    )
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars].rsplit("\n", 1)[0]
    return (cut or body[:max_chars]).strip() + "\n\n[… excerpt truncated …]"


def run_meta_seo(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Step 8 — meta title and meta description options (5 each)."""
    step_name = "meta_seo"
    context = artifacts.load_context(client_id, step_name)
    system_msg = prompts.META_SEO_PROMPT + "\n" + context
    step_label = _step_label(step_name)

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    topic_card = _load_prior_artifact(client_id, run_id, "topic_card")
    brief = _load_prior_artifact(client_id, run_id, "assignment_brief")
    fact_check = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "fact_check"
    )

    seo_ctx = editorial_input.build_meta_seo_context(
        topic_card=topic_card,
        assignment_brief=brief,
        article_source=fact_check,
        manual=manual if isinstance(manual, dict) else None,
    )

    article_excerpt = _article_excerpt_for_meta(fact_check)

    user_msg = (
        "Generate meta title and meta description options using these exact prompts:\n\n"
        "META TITLE PROMPT:\n"
        f"{seo_ctx['meta_title_prompt']}\n\n"
        "META DESCRIPTION PROMPT:\n"
        f"{seo_ctx['meta_description_prompt']}\n\n"
        "---REFERENCE MATERIAL---\n"
        f"PAGE TYPE: {seo_ctx['page_type']}\n"
        f"TARGET KEYWORD: {seo_ctx['keyword']}\n"
        f"CONTENT SUMMARY: {seo_ctx['content_description']}\n\n"
        f"---TOPIC CARD---\n{topic_card.strip() or '[missing]'}\n\n"
        f"---ASSIGNMENT BRIEF---\n{brief.strip() or '[missing]'}\n\n"
        f"---CORRECTED ARTICLE EXCERPT (fact-check)---\n{article_excerpt or '[missing]'}\n"
    )

    output = _chat_complete(system_msg, user_msg, step_label, temperature=0.65)
    output = editorial_input.finalize_meta_seo_output(output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output
