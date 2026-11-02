import logging
import threading
import time

from . import artifacts
from . import config
from . import editorial_input
from . import prompt_cache
from . import prompts
from . import faq_schema
from . import final_output_enforce
from . import french_language
from . import job_control
from .step_markers import extract_step_body, wrap_step_artifact
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
        len(prompt.workspace_text) + len(prompt.system_text),
        len(prompt.shared_docs_text),
        len(prompt.unique_text),
        "context.md" in prompt.workspace_text or "context.md" in prompt.system_text,
        prompt.session_id,
        (prompt.workspace_text or prompt.system_text)[:300].replace("\n", " "),
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


def max_tokens_for_step(step_name: str, *, word_count_target: int | None = None) -> int:
    """Output cap for this step. Draft is the only 6–8K write."""
    table = getattr(config, "STEP_MAX_TOKENS", {}) or {}
    if step_name == "draft":
        return _draft_max_tokens(word_count_target)
    try:
        return int(table.get(step_name, config.MAX_TOKENS))
    except (TypeError, ValueError):
        return config.MAX_TOKENS


def _draft_max_tokens(target: int | None) -> int:
    default = 6000
    try:
        default = int((getattr(config, "STEP_MAX_TOKENS", {}) or {}).get("draft", default))
    except (TypeError, ValueError):
        default = 6000
    if not target:
        return default
    # Long articles need a large output budget (~2 tokens/word + structure).
    return min(8192, max(default, int(target * 2.2) + 1200))


def _trim_article_by_sections(
    article: str,
    target: int,
    *,
    system_msg: str | CachedPrompt,
    outline: str = "",
    step_label: str = "section trim",
    max_passes: int = 1,
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
    max_rounds: int | None = None,
) -> str:
    """Trim the longest section or expand the shortest. Never rewrite the article."""
    from . import word_count_enforce

    low, high = editorial_input.word_count_bounds(target)
    text = (draft or "").strip()
    current = editorial_input.count_article_words(text)
    if low <= current <= high:
        return text
    rounds = config.QUALITY_RETRY_ATTEMPTS if max_rounds is None else max(1, int(max_rounds))
    if current > high:
        text = _trim_article_by_sections(
            text,
            target,
            system_msg=cached,
            outline=outline,
            step_label=f"Step {_step_num('draft') or '?'} (longest section trim)",
            max_passes=rounds,
        )
        current = editorial_input.count_article_words(text)
        if current > high:
            logger.warning(
                "draft still long after section trim: %s words (target %s, max %s)",
                current,
                target,
                high,
            )
        return text

    logger.info(
        "draft expansion: shortest section only (%s words -> min %s)",
        current,
        low,
    )
    text = word_count_enforce.expand_shortest_section(
        text,
        target,
        system_msg=cached,
        outline=outline,
        step_label=f"Step {_step_num('draft') or '?'} (shortest section expand)",
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
            "draft still short after section expand: %s words (target %s, min %s)",
            current,
            target,
            low,
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
    output = _chat_complete(
        cached,
        debug_system_message=True,
        max_tokens=max_tokens_for_step(step_name, word_count_target=wc_target),
    )
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
        max_tokens=max_tokens_for_step(step_name),
    )
    output = wrap_step_artifact(step_name, output)
    artifacts.save_artifact(client_id, run_id, step_name, output)
    logger.info("step complete %s", step_name)
    return output


def _finish_supporting_posts_text(
    output: str,
    *,
    client_id: str,
    run_id: str,
    step_label: str,
) -> str:
    output = _enforce_french(
        output,
        client_id=client_id,
        run_id=run_id,
        step_label=step_label,
        spelling=True,
    )
    wrapped = wrap_step_artifact("supporting_posts", output)
    artifacts.save_artifact(client_id, run_id, "supporting_posts", wrapped)
    logger.info("step complete supporting_posts")
    return wrapped


def _poll_supporting_posts_batch(
    client_id: str,
    run_id: str,
    batch_id: str,
    custom_id: str,
    cached: CachedPrompt,
    step_label: str,
) -> None:
    """Background: wait for the Batch API, then write the supporting-posts artifact."""
    try:
        text = claude.wait_for_batch(batch_id, custom_id=custom_id)
    except claude.BatchFailed:
        logger.exception(
            "supporting posts batch %s failed; falling back to a sync Claude call",
            batch_id,
        )
        try:
            text = _chat_complete(
                cached,
                temperature=0.55,
                max_tokens=max_tokens_for_step("supporting_posts"),
            )
        except Exception:
            logger.exception("supporting posts sync fallback also failed")
            return
    except Exception:
        logger.exception(
            "supporting posts batch %s did not complete; leaving queued artifact",
            batch_id,
        )
        return
    try:
        _finish_supporting_posts_text(
            text, client_id=client_id, run_id=run_id, step_label=step_label
        )
    except Exception:
        logger.exception("supporting posts batch %s finished but save failed", batch_id)


def _spawn_supporting_posts_poller(
    client_id: str,
    run_id: str,
    batch_id: str,
    custom_id: str,
    cached: CachedPrompt,
    step_label: str,
) -> None:
    thread = threading.Thread(
        target=_poll_supporting_posts_batch,
        args=(client_id, run_id, batch_id, custom_id, cached, step_label),
        daemon=True,
        name=f"supporting-posts-{run_id}",
    )
    thread.start()


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
    max_tok = max_tokens_for_step(step_name)
    use_batch = bool(getattr(config, "SUPPORTING_POSTS_USE_BATCH", True))
    if use_batch:
        custom_id = f"supporting-{run_id}"
        try:
            info = claude.submit_cached_batch(
                cached,
                max_tokens=max_tok,
                temperature=0.55,
                custom_id=custom_id,
            )
            batch_id = info.get("id") or ""
            queued = (
                "Supporting posts queued on the Batch API "
                f"(id={batch_id}). About 50% cheaper than a live call; "
                "not needed for the main article. Results replace this note when ready.\n"
            )
            output = wrap_step_artifact(step_name, queued)
            artifacts.save_artifact(client_id, run_id, step_name, output)
            _spawn_supporting_posts_poller(
                client_id, run_id, batch_id, custom_id, cached, step_label
            )
            logger.info(
                "supporting posts submitted to batch id=%s (non-blocking)",
                batch_id,
            )
            return output
        except Exception:
            logger.exception(
                "supporting posts batch submit failed; falling back to a sync Claude call"
            )
    output = _chat_complete(
        cached,
        temperature=0.55,
        max_tokens=max_tok,
    )
    return _finish_supporting_posts_text(
        output, client_id=client_id, run_id=run_id, step_label=step_label
    )


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
        "Use the shared TOPIC CARD, RESEARCH SUMMARY, and RESEARCH AUDIT documents above. "
        "The summary replaces the raw SERP / ATP / PAA dumps. Prefer **Research Audit → "
        "Approved FAQ questions** when present. Do not invent a parallel FAQ set. "
        "Respect LOW SIGNAL / low-demand flags.\n"
        "Prefer **Research Audit → Approved case study** for E-E-A-T proof — never invent one.\n",
        "Utilisez la fiche sujet, le résumé de recherche et l'audit de recherche partagés "
        "ci-dessus. Le résumé remplace les dumps SERP / ATP / PAA bruts. Privilégiez les "
        "questions de FAQ approuvées par l'audit (Approved FAQ questions) quand elles "
        "existent. N'inventez pas une seconde série de questions. Respectez les signaux "
        "LOW SIGNAL (demande faible).\n"
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
        max_tokens=max_tokens_for_step(step_name, word_count_target=wc_target),
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
    output = _chat_complete(cached, max_tokens=max_tokens_for_step(step_name))
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
        "Build the outline from the shared ASSIGNMENT BRIEF. Use RESEARCH SUMMARY for "
        "gaps, approved FAQ, and cite slots. Do not expect the raw SERP analysis.\n",
        "Construisez le plan à partir du brief partagé. Utilisez le RÉSUMÉ DE RECHERCHE "
        "pour les écarts, la FAQ approuvée et les citations. N'attendez pas l'analyse "
        "SERP brute. Intertitres, notes de section et plan de la FAQ sont rédigés en "
        "français, sans jargon anglais.\n",
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
    output = _chat_complete(
        cached,
        max_tokens=max_tokens_for_step(step_name, word_count_target=wc_target),
    )
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
    if not outline.strip():
        # Never draft from a stand-in: generating from "[OUTLINE MISSING]" invents structure.
        raise RuntimeError("Outline is missing: run the outline step before the draft.")
    lang = _run_language(client_id, run_id)
    unique = (
        _t(
            lang,
            "Write the draft from the shared ASSIGNMENT BRIEF, RESEARCH SUMMARY, and "
            "RESEARCH AUDIT, plus this outline. Cite only SOURCE URLS from the summary.\n\n",
            "Rédigez le brouillon à partir du brief, du résumé de recherche et de l'audit "
            "partagés ci-dessus, ainsi que de ce plan. Ne citez que les URL du résumé. "
            "Tout le texte est en français, sans mot anglais.\n\n",
        )
        + "---ARTICLE OUTLINE---\n"
        f"{outline.strip()}\n"
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
        max_tokens=max_tokens_for_step(step_name, word_count_target=wc_target),
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

    form_links = editorial_input.parse_form_internal_links(
        (artifacts.read_run_manifest(client_id, run_id) or {}).get("manual_inputs")
    )
    if form_links:
        output = final_output_enforce.inject_form_internal_links(output, form_links)

    output = faq_schema.enforce_faq_answer_length(output)
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
        "\nDo not rewrite the article. Return the report and a JSON correction list only.\n"
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
    claude_out = _chat_complete(cached, max_tokens=max_tokens_for_step(step_name))
    draft_body = extract_step_body("draft", draft) or draft
    patched, corrections = faq_schema.resolve_fact_checked_article(draft_body, claude_out)
    patched = faq_schema.enforce_faq_answer_length(patched)
    claude_out = faq_schema.embed_corrected_article(claude_out, patched, corrections)
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
    fact_check = (previous_artifact or "").strip() or _load_prior_artifact(
        client_id, run_id, "fact_check"
    )
    if not fact_check.strip():
        raise RuntimeError("Fact-check output is missing: run the fact-check step first.")
    draft = _load_prior_artifact(client_id, run_id, "draft")
    article = (
        faq_schema.extract_corrected_article_body(fact_check)
        or extract_step_body("draft", draft)
        or draft.strip()
    )
    if not article.strip():
        raise RuntimeError("No article body to publish: run draft and fact-check first.")
    logger.info(
        "final_output: applying mechanical polish + hard gates (no second article write)"
    )
    output = faq_schema.wrap_final_article(article)
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
            "Use the topic card / brief fields below and the article excerpt. "
            "Do not expect brand-voice or CTA rules for this step.\n\n",
            "Générez les options de titre méta et de description méta avec ces consignes "
            "exactes. Utilisez les champs fiche sujet / brief ci-dessous et l'extrait. "
            "Tous les titres et toutes les descriptions sont rédigés en français, sans "
            "mot anglais.\n\n",
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
    output = _chat_complete(
        cached,
        temperature=0.65,
        max_tokens=max_tokens_for_step(step_name),
    )
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
