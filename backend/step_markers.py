"""Canonical ---STEP START--- / ---STEP END--- delimiters for pipeline artifacts."""

from __future__ import annotations

STEP_MARKER_LABELS: dict[str, str] = {
    "topic_card": "TOPIC CARD",
    "serp_research": "SERP RESEARCH",
    "research": "RESEARCH",
    "assignment_brief": "BRIEF",
    "outline": "OUTLINE",
    "draft": "DRAFT",
    "fact_check": "FACT CHECK",
    "meta_seo": "META SEO",
    "final_output": "FINAL OUTPUT",
}

# Legacy delimiter labels still accepted when reading older artifacts.
LEGACY_MARKER_ALIASES: dict[str, tuple[str, str]] = {
    "final_output": ("---FINAL ARTICLE START---", "---FINAL ARTICLE END---"),
    "research": ("---SERP ANALYSIS START---", "---SERP ANALYSIS END---"),
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
    legacy = LEGACY_MARKER_ALIASES.get(step_key)
    if legacy and legacy not in pairs:
        pairs.append(legacy)
    return pairs


def wrap_step_artifact(step_key: str, body: str) -> str:
    """Ensure artifact body is wrapped in canonical step delimiters."""
    text = (body or "").strip()
    if not text:
        return ""
    start, end = step_markers(step_key)
    if start in text and end in text:
        return text + ("\n" if not text.endswith("\n") else "")
    return f"{start}\n{text}\n{end}\n"


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
