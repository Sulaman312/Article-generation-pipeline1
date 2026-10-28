import logging
import time

from . import artifacts
from . import config
from . import editorial_input
from . import prompt_cache
from . import prompts
from .context_extractor import extract_for_step_7
from . import faq_schema
from . import final_output_enforce
from . import french_language
from . import job_control
from .step_markers import wrap_step_artifact
from . import writing_format_enforce
from .integrations import anthropic as claude
from .pipeline_steps import ARTICLE_STEP_ORDER
from .prompt_cache import CachedPrompt

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


def _debug_log_cached_prompt(prompt: CachedPrompt) -> None:
    logger.debug(
        "%s cache_prefix~%s_tokens system_len=%s shared_len=%s unique_len=%s "
        "has_context_md=%s session=%s preview=%s",
        prompt.step_label,
        prompt.prefix_token_estimate,
        len(prompt.system_text),
        len(prompt.shared_docs_text),
        len(prompt.unique_text),
        "context.md" in prompt.system_text,
        prompt.session_id,
        prompt.system_text[:300].replace("\n", " "),
    )


def _load_prior_artifact(client_id: str, run_id: str, step_name: str) -> str:
    try:
        return artifacts.load_artifact(client_id, run_id, step_name)
    except FileNotFoundError:
        return ""


def _run_language(client_id: str, run_id: str) -> str:
    """Article language for this run (``fr`` triggers the French quality layer)."""
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    return editorial_input.article_language_from_manual(
        manual if isinstance(manual, dict) else None
    )


def _t(lang: str, en: str, fr: str) -> str:
    """Pick the instruction text in the run language (prompts are French for French runs)."""
    return fr if (lang or "").lower() == "fr" else en


def _french_glossary(client_id: str):
    return french_language.load_glossary(client_id)


def _enforce_french(
    text: str,
    *,
    client_id: str,
    run_id: str,
    step_label: str,
    spelling: bool = False,
) -> str:
    """Retry-until-clean French check for brief / outline / supporting posts.

    No-op for non-French runs. Raises ``FrenchQualityError`` after the retries.
    """
    if not config.FRENCH_QA_ENABLED or _run_language(client_id, run_id) != "fr":
        return text
    return french_language.enforce_french_artifact(
        text,
        step_label=step_label,
        glossary=_french_glossary(client_id),
        spelling=spelling and config.FRENCH_SPELLCHECK_ENABLED,
        attempts=config.QUALITY_RETRY_ATTEMPTS,
    )


def _retry_call(fn, *, label: str, attempts: int | None = None, delay: float = 3.0):
    """Run ``fn`` up to ``attempts`` times; raise (never substitute text) if all fail."""
    tries = attempts or config.QUALITY_RETRY_ATTEMPTS
    last: Exception | None = None
    for i in range(tries):
        job_control.raise_if_cancelled()
        try:
            return fn()
        except job_control.JobCancelled:
            raise
        except Exception as e:
            last = e
            logger.warning("%s: attempt %s/%s failed: %s", label, i + 1, tries, e)
            if i + 1 < tries:
                time.sleep(delay)
    raise RuntimeError(f"{label} failed after {tries} attempts: {last}") from last


def _cached_prompt(
    client_id: str,
    run_id: str,
    *,
    step_prompt: str,
    unique_suffix: str,
    step_label: str,
    wc_target: int | None = None,
    step_name: str = "",
) -> CachedPrompt:
    """Build Phase-2 layout: client system + shared docs + step prompt/unique."""
    suffix = (unique_suffix or "").strip()
    if wc_target:
        # Word-count overrides vary per article — always after the cache breakpoint.
        wc_block = editorial_input.system_word_count_override(wc_target).strip()
        suffix = f"{wc_block}\n\n{suffix}".strip() if suffix else wc_block
    return prompt_cache.build_cached_prompt(
        client_id=client_id,
        run_id=run_id,
        step_prompt=step_prompt,
        unique_suffix=suffix,
        step_label=step_label,
        lang=_run_language(client_id, run_id),
        step_name=step_name,
    )


def _chat_complete(
    system_msg: str | CachedPrompt,
    user_msg: str | None = None,
    step_label: str = "pipeline step",
    *,
    debug_system_message: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    if isinstance(system_msg, CachedPrompt):
        if debug_system_message:
            _debug_log_cached_prompt(system_msg)
        return claude.chat_complete(
            system_msg,
            step_label=system_msg.step_label or step_label,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    if debug_system_message and isinstance(system_msg, str):
        logger.debug(
            "%s system_len=%s has_context_md=%s preview=%s",
            step_label,
            len(system_msg),
            "context.md" in system_msg,
            system_msg[:300].replace("\n", " "),
        )
    return claude.chat_complete(
        system_msg,
        user_msg or "",
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
    lang = (
        editorial_input.article_language_from_manual(manual)
        if isinstance(manual, dict)
        else "en"
    )
    return (
        notes
        + editorial_input.internal_links_editorial_notice(
            manual if isinstance(manual, dict) else None
        )
        + editorial_input.seo_readability_notice(lang)
        + editorial_input.writing_format_guidelines_notice()
        + _faq_notice_for_run(client_id, run_id)
        + _external_links_notice_for_run(client_id, run_id)
    )


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
    system_msg: str | CachedPrompt,
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
    cached: CachedPrompt,
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
            system_msg=cached,
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
        expand_unique = (
            f"{prompts.DRAFT_PROMPT.strip()}\n\n"
            f"---STEP-SPECIFIC INPUT---\n"
            f"The draft below is TOO SHORT and must be expanded.\n"
            f"- Current BODY word count: {current:,} (FAQ is excluded from this count)\n"
            f"- Editor form target: {target:,} words\n"
            f"- Acceptable minimum: {low:,} words (maximum ~{high:,})\n"
            f"- Add approximately {shortage:,} more words of substantive BODY prose.\n\n"
            f"Rules:\n"
            f"- Keep the same H1/H2 structure and markdown format.\n"
            f"- Expand every major BODY H2 with examples, steps, and detail.\n"
            f"- Do NOT add words to the FAQ section. FAQ answers stay 2-4 sentence paragraphs.\n"
            f"- Hit the word count in the article content only. FAQ does not count.\n"
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
            cached.with_unique(
                expand_unique,
                step_label=f"Step {_step_num('draft') or '?'} (draft expansion {round_i + 1})",
            ),
            max_tokens=_draft_max_tokens(target),
            temperature=0.5,
        )
        current = editorial_input.count_article_words(text)
        if current > high:
            text = _trim_article_by_sections(
                text,
                target,
                system_msg=cached,
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
    wc_target = _word_count_target_for_run(client_id, run_id)
    step_label = _step_label(step_name)

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    built = (
        editorial_input.build_topic_payload(manual)
        if isinstance(manual, dict)
        else ""
    )
    unique = (built or previous_artifact or "").strip()
    if isinstance(manual, dict):
        unique += editorial_input.notes_editorial_notice(manual)
        unique += editorial_input.internal_links_editorial_notice(manual)
    unique += editorial_input.seo_readability_notice(
        editorial_input.article_language_from_manual(manual)
        if isinstance(manual, dict)
        else "en"
    )
    if wc_target:
        unique += editorial_input.mandatory_word_count_notice(wc_target)
    unique = _with_word_count_user(unique, wc_target)

    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.TOPIC_CARD_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        wc_target=wc_target,
        step_name=step_name,
    )
    output = _chat_complete(cached, debug_system_message=True)
    if wc_target:
        output = editorial_input.enforce_word_count_in_topic_card(output, wc_target)
    if isinstance(manual, dict):
        output = editorial_input.apply_manual_keywords_topic_card(
            output, manual, semrush_notes=""
        )
    output = wrap_step_artifact(step_name, output)
    if isinstance(manual, dict):
        output = editorial_input.apply_manual_internal_links_topic_card(output, manual)
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


def _research_language_note(client_id: str, run_id: str, notes: str) -> str:
    """Append the French-only rule to the notes sent to the research model."""
    if _run_language(client_id, run_id) != "fr":
        return notes
    rule = (
        "Langue : le contenu produit (questions, réponses, résumés) doit être entièrement "
        "en français. Aucun mot anglais (bol, collation, formule... et non bowl, snack, pack)."
    )
    return f"{notes}\n\n{rule}".strip() if notes else rule


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

    notes = _research_language_note(client_id, run_id, notes)
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

    notes = _research_language_note(client_id, run_id, notes)
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
    step_label = _step_label(step_name)

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    notes = editorial_input.notes_from_manual(manual) if isinstance(manual, dict) else ""
    keyword_data = _keyword_data_from_manual(manual if isinstance(manual, dict) else None)

    case_study = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "case_study_research"
    )
    # Shared docs already carry topic/SERP/ATP/PAA/audit/brief; put only
    # audit-specific extras after the breakpoint (case study, keyword paste, notes).
    lang = _run_language(client_id, run_id)
    unique = (
        _t(
            lang,
            "Audit the shared research documents above. Reject fabricated brands, prices, "
            "stats, and dead/FAIL URLs. Approve only what draft/brief may use.\n\n",
            "Auditez les documents de recherche partagés ci-dessus. Rejetez les marques, "
            "prix et statistiques inventés ainsi que les adresses mortes ou en échec "
            "(FAIL). N'approuvez que ce que le brouillon et le brief peuvent utiliser. "
            "Rédigez vos décisions et les questions de FAQ approuvées en français.\n\n",
        )
        + f"---CASE STUDY RESEARCH (includes URL verification)---\n"
        f"{case_study.strip() or '[none]'}\n\n"
        f"---SERP RESEARCH DIGEST (raw Perplexity)---\n"
        f"{_load_prior_artifact(client_id, run_id, 'serp_research').strip() or '[none]'}\n\n"
        f"---KEYWORD / ATP PASTE (optional)---\n"
        f"{keyword_data or '[none]'}\n\n"
        f"---EDITOR NOTES---\n"
        f"{notes or '[none]'}\n"
    )
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.RESEARCH_AUDIT_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        step_name=step_name,
    )
    output = _chat_complete(
        cached,
        temperature=0.2,
        max_tokens=3500,
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_supporting_posts(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Claude drafts supporting blog posts from the audited ATP cluster."""
    step_name = "supporting_posts"
    step_label = _step_label(step_name)

    draft = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "draft"
    )
    outline = _load_prior_artifact(client_id, run_id, "outline")
    lang = _run_language(client_id, run_id)
    unique = (
        _t(
            lang,
            "Use the shared RESEARCH AUDIT and ATP TOPIC RESEARCH documents above as the "
            "mandatory gate. Follow APPROVED sections only.\n\n",
            "Utilisez l'audit de recherche (RESEARCH AUDIT) et la recherche thématique "
            "(ATP TOPIC RESEARCH) ci-dessus comme filtre obligatoire. Ne suivez que les "
            "sections APPROVED. Rédigez tout en français.\n\n",
        )
        + "---MAIN ARTICLE DRAFT---\n"
        f"{draft.strip() or '[draft missing — use outline titles for interlinks]'}\n\n"
        f"---MAIN ARTICLE OUTLINE---\n"
        f"{outline.strip() or '[none]'}\n"
    )
    unique += _editorial_notices_for_run(client_id, run_id)
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.SUPPORTING_POSTS_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        step_name=step_name,
    )
    output = _chat_complete(
        cached,
        temperature=0.55,
        max_tokens=8000,
    )
    output = _enforce_french(
        output,
        client_id=client_id,
        run_id=run_id,
        step_label=step_label,
        spelling=True,
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

    notes = _research_language_note(client_id, run_id, notes)
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


def run_step_2(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "assignment_brief"
    wc_target = _word_count_target_for_run(client_id, run_id)
    step_label = _step_label(step_name)
    lang = _run_language(client_id, run_id)
    unique = _t(
        lang,
        "Use the shared TOPIC CARD, SERP ANALYSIS, ATP, PAA, and RESEARCH AUDIT documents "
        "above. Prefer **Research Audit → Approved FAQ questions** when present; otherwise "
        "use the Source Research FAQ bank. Do not invent a parallel FAQ set. "
        "Respect LOW SIGNAL / low-demand flags.\n"
        "Prefer **Research Audit → Approved case study** for E-E-A-T proof — never invent one.\n",
        "Utilisez la fiche sujet, l'analyse des résultats de recherche, la recherche "
        "thématique, la banque de questions et l'audit de recherche partagés ci-dessus. "
        "Privilégiez les questions de FAQ approuvées par l'audit (Approved FAQ questions) "
        "quand elles existent, sinon la banque de questions de la recherche. N'inventez "
        "pas une seconde série de questions. Respectez les signaux LOW SIGNAL (demande "
        "faible).\n"
        "Pour la preuve d'expérience (E-E-A-T), privilégiez l'étude de cas approuvée par "
        "l'audit (Approved case study) : n'en inventez jamais.\n"
        "Rédigez tout le brief en français, sans jargon anglais : les consignes "
        "destinées au rédacteur sont aussi en français.\n",
    )
    unique += _editorial_notices_for_run(client_id, run_id)
    if wc_target:
        unique += editorial_input.mandatory_word_count_notice(wc_target)
    unique = _with_word_count_user(unique, wc_target)
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.ASSIGNMENT_BRIEF_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        wc_target=wc_target,
        step_name=step_name,
    )
    output = _chat_complete(
        cached,
        debug_system_message=True,
    )
    if wc_target:
        output = editorial_input.enforce_word_count_in_brief(output, wc_target)
    output = writing_format_enforce.enforce_brief(output, allow_llm_repair=True)
    # French runs: English jargon in a brief is copied downstream. Retry, never pass it on.
    output = _enforce_french(
        output, client_id=client_id, run_id=run_id, step_label=step_label
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_3(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "research"
    step_label = _step_label(step_name)
    serp_digest = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "serp_research"
    )
    if not serp_digest.strip():
        raise RuntimeError("SERP research is missing: run serp_research before the analysis.")
    lang = _run_language(client_id, run_id)
    unique = (
        _t(
            lang,
            "Produce the SERP analysis from the shared TOPIC CARD above and this "
            "SERP research digest.\n\n",
            "Produisez l'analyse des résultats de recherche à partir de la fiche sujet "
            "partagée ci-dessus et de ce condensé de recherche. Rédigez en français, en "
            "traduisant les titres de concurrents et le jargon anglais.\n\n",
        )
        + "---SERP RESEARCH DIGEST---\n"
        f"{serp_digest.strip()}\n"
    )
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.RESEARCH_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        step_name=step_name,
    )
    output = _chat_complete(cached)
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_4(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "outline"
    wc_target = _word_count_target_for_run(client_id, run_id)
    step_label = _step_label(step_name)
    lang = _run_language(client_id, run_id)
    unique = _t(
        lang,
        "Build the outline from the shared ASSIGNMENT BRIEF, SERP ANALYSIS, "
        "RESEARCH AUDIT, ATP, and PAA documents above.\n",
        "Construisez le plan à partir du brief, de l'analyse des résultats de recherche, "
        "de l'audit de recherche, de la recherche thématique et de la banque de questions "
        "partagés ci-dessus. Intertitres, notes de section et plan de la FAQ sont "
        "rédigés en français, sans jargon anglais.\n",
    )
    unique += _editorial_notices_for_run(client_id, run_id)
    unique += editorial_input.outline_format_guidelines_notice()
    if wc_target:
        unique += editorial_input.mandatory_word_count_notice(wc_target)
    unique = _with_word_count_user(unique, wc_target)
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.OUTLINE_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        wc_target=wc_target,
        step_name=step_name,
    )
    output = _chat_complete(cached)
    if wc_target:
        output = editorial_input.enforce_outline_section_word_counts(output, wc_target)
    output = writing_format_enforce.enforce_outline(output, allow_llm_repair=True)
    output = _enforce_french(
        output, client_id=client_id, run_id=run_id, step_label=step_label
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def run_step_5(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    step_name = "draft"
    wc_target = _word_count_target_for_run(client_id, run_id)
    step_label = _step_label(step_name)
    outline = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "outline"
    )
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    if not outline.strip():
        # Never draft from a stand-in: generating from "[OUTLINE MISSING]" invents structure.
        raise RuntimeError("Outline is missing: run the outline step before the draft.")
    lang = _run_language(client_id, run_id)
    unique = (
        _t(
            lang,
            "Write the draft from the shared BRIEF / SERP ANALYSIS / ATP / PAA / AUDIT "
            "documents and this outline.\n\n",
            "Rédigez le brouillon à partir du brief, de l'analyse des résultats de "
            "recherche, de la recherche thématique, de la banque de questions et de "
            "l'audit partagés ci-dessus, ainsi que de ce plan. Tout le texte est en "
            "français, sans mot anglais.\n\n",
        )
        + "---ARTICLE OUTLINE---\n"
        f"{outline.strip()}\n\n"
        "---SERP RESEARCH DIGEST (use for external source URLs)---\n"
        f"{serp_digest.strip() or '[No SERP digest — cite only URLs you can justify from research]'}\n"
    )
    unique += _editorial_notices_for_run(client_id, run_id)
    if wc_target:
        unique += editorial_input.mandatory_word_count_notice(wc_target)
        unique += editorial_input.draft_word_count_requirement(wc_target)
        unique += editorial_input.draft_section_budget_guidance(outline, wc_target)
    unique = _with_word_count_user(unique, wc_target)
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.DRAFT_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        wc_target=wc_target,
        step_name=step_name,
    )
    output = _chat_complete(
        cached,
        debug_system_message=True,
        max_tokens=_draft_max_tokens(wc_target),
        temperature=0.55,
    )
    if wc_target:
        output = _ensure_draft_word_count(
            output,
            wc_target,
            cached=cached,
            outline=outline,
        )
        words = editorial_input.count_article_words(output)
        logger.info(
            "draft word count after generation enforce %s (target %s)",
            words,
            wc_target,
        )
    draft_lang = editorial_input.article_language_from_manual(
        (artifacts.read_run_manifest(client_id, run_id) or {}).get("manual_inputs")
    )
    output = writing_format_enforce.enforce_article(
        output, stage="draft", allow_llm_repair=True, lang=draft_lang
    )
    # Format repair can inflate length — re-assert the generation window.
    if wc_target:
        low, high = editorial_input.word_count_bounds(wc_target)
        words = editorial_input.count_article_words(output)
        if words < low or words > high:
            output = _ensure_draft_word_count(
                output,
                wc_target,
                cached=cached,
                outline=outline,
            )
            words = editorial_input.count_article_words(output)
        logger.info("draft final word count %s (target %s)", words, wc_target)
    from . import final_output_enforce
    from . import hard_gates

    form_links = editorial_input.parse_form_internal_links(
        (artifacts.read_run_manifest(client_id, run_id) or {}).get("manual_inputs")
    )
    if form_links:
        output = final_output_enforce.inject_form_internal_links(output, form_links)

    output = faq_schema.enforce_faq_answer_length(output)

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
    step_label = _step_label(step_name)

    draft = _load_prior_artifact(client_id, run_id, "draft").strip() or (
        previous_artifact or ""
    ).strip()
    lang = _run_language(client_id, run_id)
    ppx_block = ""
    if config.PERPLEXITY_API_KEY:
        from .integrations import perplexity as ppx

        # Retry, then fail the step. A "FAILED" note must never be passed on as if it
        # were research.
        ppx_block = _retry_call(
            lambda: ppx.run_sonar_draft_factcheck(draft),
            label="Perplexity draft fact-check",
        )
    else:
        ppx_block = _t(
            lang,
            "[Perplexity web fact-check skipped — set PERPLEXITY_API_KEY in `.env` "
            "to run an automatic web scan before the editor fact-check.]",
            "[Vérification web Perplexity non exécutée : aucune clé PERPLEXITY_API_KEY "
            "n'est configurée.]",
        )

    wc_target = _word_count_target_for_run(client_id, run_id)
    unique = (
        f"---ARTICLE DRAFT---\n"
        f"{draft}\n\n"
        "---PERPLEXITY WEB FACT-CHECK (raw signals — verify independently)---\n"
        f"{ppx_block}\n"
    )
    if wc_target:
        low, high = editorial_input.word_count_bounds(wc_target)
        draft_words = editorial_input.count_article_words(draft)
        unique += (
            f"\n\n=== LENGTH PRESERVATION (NON-NEGOTIABLE) ===\n"
            f"The draft body is already written to length "
            f"({draft_words:,} words; form target {wc_target:,}, band {low:,}–{high:,}).\n"
            f"In ---CORRECTED ARTICLE--- keep nearly the same body length. "
            f"Fix facts/clarity; do NOT expand into a longer rewrite. "
            f"FAQ answers stay 2-4 sentence paragraphs and do not count toward the band.\n"
        )
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.FACT_CHECK_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        wc_target=wc_target,
        step_name=step_name,
    )
    claude_out = _chat_complete(cached)
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
                    system_msg=cached,
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
    corrected = faq_schema.extract_corrected_article_body(claude_out)
    if corrected:
        tightened = faq_schema.enforce_faq_answer_length(corrected)
        if tightened != corrected:
            start = claude_out.find(faq_schema.CORRECTED_ARTICLE_START)
            end = claude_out.find(faq_schema.CORRECTED_ARTICLE_END)
            if start != -1 and end != -1 and end > start:
                claude_out = (
                    claude_out[: start + len(faq_schema.CORRECTED_ARTICLE_START)]
                    + "\n"
                    + tightened.strip()
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
    extracted = extract_for_step_7(client_id)

    form_links = editorial_input.parse_form_internal_links(
        (artifacts.read_run_manifest(client_id, run_id) or {}).get("manual_inputs")
    )
    form_link_lines = (
        "\n".join(
            f"- {item.get('title') or 'page'} → {editorial_input.form_internal_link_href(item)}"
            for item in form_links
        )
        if form_links
        else "None listed on the article form."
    )
    cta_href = (extracted.get("cta_href") or "").strip() or "/contact"
    has_html_cta = bool(extracted.get("has_cta_html_template"))
    wc_target = _word_count_target_for_run(client_id, run_id)
    step_label = _step_label(step_name)
    serp_digest = _load_prior_artifact(client_id, run_id, "serp_research")
    fact_check = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "fact_check"
    )
    if not fact_check.strip():
        raise RuntimeError("Fact-check output is missing: run the fact-check step first.")
    lang = _run_language(client_id, run_id)
    # Client clusters/CTA live in the cached system prompt; form links vary per article.
    unique = (
        _t(
            lang,
            "",
            "Finalisez l'article en français : tout le texte publié (titres, tableaux, "
            "FAQ, appels à l'action, légendes d'images) est en français, sans mot "
            "anglais. Chaque réponse de FAQ répond à sa question.\n\n",
        )
        + "---ARTICLE-FORM INTERNAL LINKS (place these first, exact hrefs)---\n"
        f"{form_link_lines}\n\n"
        f"{fact_check.strip()}\n\n"
        "---SOURCES FOR EXTERNAL LINKS (URLs must appear here — do not invent)---\n"
        f"---SERP RESEARCH DIGEST---\n{serp_digest.strip()}\n\n"
        "Shared SERP ANALYSIS is in the documents above — cite only URLs that appear "
        "in these sources.\n"
        "---END SOURCES---\n"
    )
    unique += _editorial_notices_for_run(client_id, run_id)
    unique += editorial_input.cta_format_guidelines_notice(
        cta_href, has_html_template=has_html_cta
    )
    if wc_target:
        unique += editorial_input.mandatory_word_count_notice(wc_target)
        unique += editorial_input.draft_word_count_requirement(wc_target)
        unique += (
            "\n=== FINAL OUTPUT LENGTH ===\n"
            "The corrected article was written to the form word band. "
            "Publish with nearly the same body length — do not expand. "
            "Use section budgets from the outline; FAQ stays extra (not counted).\n"
        )
    unique = _with_word_count_user(unique, wc_target)
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.FINAL_OUTPUT_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        wc_target=wc_target,
        step_name=step_name,
    )
    output = _chat_complete(
        cached,
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

    lang = _run_language(client_id, run_id)
    unique = (
        _t(
            lang,
            "Generate meta title and meta description options using these exact prompts. "
            "Shared TOPIC CARD and ASSIGNMENT BRIEF are in the documents above.\n\n",
            "Générez les options de titre méta et de description méta avec ces consignes "
            "exactes. La fiche sujet et le brief partagés sont ci-dessus. Tous les titres "
            "et toutes les descriptions sont rédigés en français, sans mot anglais.\n\n",
        )
        + "META TITLE PROMPT:\n"
        f"{seo_ctx['meta_title_prompt']}\n\n"
        "META DESCRIPTION PROMPT:\n"
        f"{seo_ctx['meta_description_prompt']}\n\n"
        "---REFERENCE MATERIAL---\n"
        f"PAGE TYPE: {seo_ctx['page_type']}\n"
        f"TARGET KEYWORD: {seo_ctx['keyword']}\n"
        f"CONTENT SUMMARY: {seo_ctx['content_description']}\n\n"
        f"---CORRECTED ARTICLE EXCERPT (fact-check)---\n{article_excerpt or '[missing]'}\n"
    )
    cached = _cached_prompt(
        client_id,
        run_id,
        step_prompt=prompts.META_SEO_PROMPT,
        unique_suffix=unique,
        step_label=step_label,
        step_name=step_name,
    )
    output = _chat_complete(cached, temperature=0.65)
    # Strip echoed prompt text first so only the real options are checked.
    output = editorial_input.finalize_meta_seo_output(output)
    output = _enforce_french(
        output,
        client_id=client_id,
        run_id=run_id,
        step_label=step_label,
        spelling=True,
    )
    output = editorial_input.finalize_meta_seo_output(output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output
