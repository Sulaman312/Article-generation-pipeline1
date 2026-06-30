"""Pipeline system prompts loaded from Markdown files (`steps/`).

Edit the `.md` files to change wording; imports stay stable:

    from backend import prompts
    prompts.STEP_3_PROMPT
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent / "steps"
_ROOT_PROMPTS_DIR = Path(__file__).resolve().parent


def _load_md(filename: str) -> str:
    path = (_PROMPTS_DIR / filename) if not filename.startswith("..") else (
        _ROOT_PROMPTS_DIR / filename.removeprefix("../")
    )
    text = path.read_text(encoding="utf-8")
    if text.endswith("\n"):
        return text
    return text + "\n"


STEP_1_PROMPT = _load_md("01_topic_card.md")
STEP_2_PROMPT = _load_md("02_assignment_brief.md")
STEP_3_PROMPT = _load_md("03_research.md")
STEP_4_PROMPT = _load_md("04_outline.md")
STEP_5_PROMPT = _load_md("05_draft.md")
STEP_6_PROMPT = _load_md("06_fact_check.md")
STEP_7_PROMPT = _load_md("07_final_output.md")

# Semantic aliases. The numeric STEP_* constants follow the on-disk markdown filenames
# and intentionally do NOT include the `serp_research` pipeline step.
TOPIC_CARD_PROMPT = STEP_1_PROMPT
ASSIGNMENT_BRIEF_PROMPT = STEP_2_PROMPT
RESEARCH_PROMPT = STEP_3_PROMPT
OUTLINE_PROMPT = STEP_4_PROMPT
DRAFT_PROMPT = STEP_5_PROMPT
FACT_CHECK_PROMPT = STEP_6_PROMPT
FINAL_OUTPUT_PROMPT = STEP_7_PROMPT
WRITING_FORMAT_GUIDELINES = _load_md("../writing_format_guidelines.md")

WRITING_FORMAT_BLOCK = (
    "\n\n--- WRITING FORMAT GUIDELINES (canonical — auto-checked after generation) ---\n"
    f"{WRITING_FORMAT_GUIDELINES.strip()}\n"
    "--- END WRITING FORMAT GUIDELINES ---\n"
)


def with_writing_format_guidelines(step_prompt: str) -> str:
    """Append canonical format rules once to a step system prompt."""
    base = step_prompt.rstrip()
    if "WRITING FORMAT GUIDELINES (canonical" in base:
        return base + "\n"
    return base + WRITING_FORMAT_BLOCK


__all__ = [
    "STEP_1_PROMPT",
    "STEP_2_PROMPT",
    "STEP_3_PROMPT",
    "STEP_4_PROMPT",
    "STEP_5_PROMPT",
    "STEP_6_PROMPT",
    "STEP_7_PROMPT",
    "TOPIC_CARD_PROMPT",
    "ASSIGNMENT_BRIEF_PROMPT",
    "RESEARCH_PROMPT",
    "OUTLINE_PROMPT",
    "DRAFT_PROMPT",
    "FACT_CHECK_PROMPT",
    "FINAL_OUTPUT_PROMPT",
    "WRITING_FORMAT_GUIDELINES",
    "WRITING_FORMAT_BLOCK",
    "with_writing_format_guidelines",
]
