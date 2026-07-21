"""Canonical ---STEP START--- / ---STEP END--- delimiters for pipeline artifacts."""

from __future__ import annotations

STEP_MARKER_LABELS: dict[str, str] = {
    "topic_card": "TOPIC CARD",
    "serp_research": "SERP RESEARCH",
    "research": "SERP ANALYSIS",
    "source_research": "SOURCE RESEARCH",
    # Sub-artifacts still written inside Source Research / Draft (not UI steps).
    "atp_topic_research": "ATP TOPIC RESEARCH",
    "paa_faq_research": "PAA FAQ RESEARCH",
    "case_study_research": "CASE STUDY RESEARCH",
    "research_audit": "RESEARCH AUDIT",
    "assignment_brief": "BRIEF",
    "outline": "OUTLINE",
    "draft": "DRAFT",
    "supporting_posts": "SUPPORTING POSTS",
    "fact_check": "FACT CHECK",
    "meta_seo": "META SEO",
    "final_output": "FINAL OUTPUT",
}

# Legacy delimiter labels still accepted when reading older artifacts.
LEGACY_MARKER_ALIASES: dict[str, list[tuple[str, str]]] = {
    "final_output": [("---FINAL ARTICLE START---", "---FINAL ARTICLE END---")],
    "research": [("---RESEARCH START---", "---RESEARCH END---")],
}


def step_marker_label(step_key: str) -> str:
    try:
        return STEP_MARKER_LABELS[step_key]
    except KeyError as e:
        raise KeyError(f"Unknown pipeline step for markers: {step_key!r}") from e


def step_markers(step_key: str) -> tuple[str, str]:
    label = step_marker_label(step_key)
    return (f"---{label} START---", f"---{label} END---")


def marker_pairs_for_step(step_key: str) -> list[tuple[str, str]]:
    pairs = [step_markers(step_key)]
    for legacy in LEGACY_MARKER_ALIASES.get(step_key, ()):
        if legacy not in pairs:
            pairs.append(legacy)
    return pairs


def has_step_markers(step_key: str, text: str) -> bool:
    """True when the artifact already includes a canonical or legacy START/END pair."""
    raw = text or ""
    for start, end in marker_pairs_for_step(step_key):
        s = raw.find(start)
        e = raw.find(end)
        if s != -1 and e != -1 and e > s:
            return True
    return False


def _strip_orphan_step_markers(text: str, start: str, end: str) -> str:
    """Peel leading/trailing canonical markers so wrapping never nests duplicates."""
    t = (text or "").strip()
    changed = True
    while changed and t:
        changed = False
        if t.startswith(start):
            t = t[len(start) :].lstrip("\n").strip()
            changed = True
            continue
        if t.endswith(end):
            t = t[: -len(end)].rstrip("\n").strip()
            changed = True
            continue
        first, sep, rest = t.partition("\n")
        if sep and first.strip() == start:
            t = rest.strip()
            changed = True
            continue
        last_nl = t.rfind("\n")
        if last_nl != -1 and t[last_nl + 1 :].strip() == end:
            t = t[:last_nl].strip()
            changed = True
            continue
    return t


def wrap_step_artifact(step_key: str, body: str) -> str:
    """Ensure artifact body is wrapped in canonical step delimiters (exactly once)."""
    text = (body or "").strip()
    if not text:
        return ""
    start, end = step_markers(step_key)
    if has_step_markers(step_key, text):
        inner = extract_step_body(step_key, text)
    else:
        inner = text
    inner = _strip_orphan_step_markers(inner, start, end)
    return f"{start}\n{inner.strip()}\n{end}\n"


def ensure_step_markers(step_key: str, body: str) -> str:
    """Idempotent wrap used on save.

    Fact-check may keep a Perplexity audit trail *before* the canonical pair — leave
    that intact when markers are already present. All other steps are normalized to
    a single START/END wrapper (fixes nested model-emitted markers).
    """
    if step_key not in STEP_MARKER_LABELS:
        text = body or ""
        return text if not text or text.endswith("\n") else text + "\n"
    stripped = (body or "").strip()
    if not stripped:
        return ""
    if step_key == "fact_check" and has_step_markers(step_key, stripped):
        return stripped if stripped.endswith("\n") else stripped + "\n"
    return wrap_step_artifact(step_key, stripped)


def extract_step_body(step_key: str, text: str) -> str:
    """Return inner body for a step artifact (supports legacy marker pairs)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    for start, end in marker_pairs_for_step(step_key):
        s = raw.find(start)
        e = raw.find(end)
        if s != -1 and e != -1 and e > s:
            return raw[s + len(start) : e].strip()
    return raw
