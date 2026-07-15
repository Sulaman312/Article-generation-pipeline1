"""Canonical ---STEP START--- / ---STEP END--- delimiters for pipeline artifacts."""

from __future__ import annotations

STEP_MARKER_LABELS: dict[str, str] = {
    "topic_card": "TOPIC CARD",
    "serp_research": "SERP RESEARCH",
    "research": "SERP ANALYSIS",
    "assignment_brief": "BRIEF",
    "outline": "OUTLINE",
    "draft": "DRAFT",
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


def wrap_step_artifact(step_key: str, body: str) -> str:
    """Ensure artifact body is wrapped in canonical step delimiters."""
    text = (body or "").strip()
    if not text:
        return ""
    inner = extract_step_body(step_key, text) or text
    start, end = step_markers(step_key)
    return f"{start}\n{inner.strip()}\n{end}\n"


def ensure_step_markers(step_key: str, body: str) -> str:
    """Idempotent wrap used on save — never strips prefixes outside an existing pair.

    If canonical/legacy markers already exist, the full document is left intact
    (important for fact_check audit trail before ``---FACT CHECK START---``).
    Otherwise the body is wrapped in the canonical START/END pair.
    """
    if step_key not in STEP_MARKER_LABELS:
        text = body or ""
        return text if not text or text.endswith("\n") else text + "\n"
    stripped = (body or "").strip()
    if not stripped:
        return ""
    start, end = step_markers(step_key)
    if start in stripped and end in stripped:
        return stripped if stripped.endswith("\n") else stripped + "\n"
    if has_step_markers(step_key, stripped):
        # Legacy-only → rewrite to canonical markers.
        return wrap_step_artifact(step_key, stripped)
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
