import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = _BACKEND_ROOT.parent

# Project `.env` wins over stale shell exports (e.g. MONGODB_DB from another repo).
load_dotenv(REPO_ROOT / ".env", override=True)

_project_env = (os.getenv("APP_PROJECT_ENV_FILE") or "").strip()
if _project_env:
    _project_path = Path(_project_env)
    if not _project_path.is_absolute():
        _project_path = REPO_ROOT / _project_path
    if _project_path.is_file():
        load_dotenv(_project_path, override=True)

# Anthropic Claude — all editorial LLM steps (topic card, research, draft, …)
# For OpenRouter: put the OpenRouter key in ANTHROPIC_API_KEY and set
# ANTHROPIC_BASE_URL=https://openrouter.ai/api plus an OpenRouter model slug.
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None


def normalize_base_url(raw: str | None) -> str | None:
    """Clean a base URL from env: strip quotes/space, default to https:// if no scheme.

    Hosting dashboards often store ``openrouter.ai/api`` without the scheme, which
    makes httpx fail with "Request URL is missing an 'http://' or 'https://' protocol".
    """
    value = (raw or "").strip().strip("\"'").strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    return value.rstrip("/")


ANTHROPIC_BASE_URL = normalize_base_url(os.getenv("ANTHROPIC_BASE_URL"))
CLAUDE_MODEL = (os.getenv("CLAUDE_MODEL") or "claude-sonnet-4-6").strip()
MAX_TOKENS = 4000
TEMPERATURE = 0.7

# Prompt caching (Anthropic via OpenRouter or direct). Phase 2: stable system +
# shared-docs user block with cache_control; session_id pins OpenRouter routing.
PROMPT_CACHE_ENABLED = (os.getenv("PROMPT_CACHE_ENABLED") or "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
# Empty = provider default (5m). Set "1h" for longer interactive article runs.
PROMPT_CACHE_TTL = (os.getenv("PROMPT_CACHE_TTL") or "1h").strip()
try:
    PROMPT_CACHE_MIN_TOKENS = int(os.getenv("PROMPT_CACHE_MIN_TOKENS") or "1024")
except ValueError:
    PROMPT_CACHE_MIN_TOKENS = 1024

MONGODB_URI = (os.getenv("MONGODB_URI") or "").strip() or None
MONGODB_DB = (
    os.getenv("MONGODB_DB") or "article_generation_pipeline"
).strip() or "article_generation_pipeline"

# Login — default admin is seeded into MongoDB `users` on startup (hashed).
AUTH_DEFAULT_USERNAME = (os.getenv("AUTH_DEFAULT_USERNAME") or "admin").strip() or "admin"
AUTH_DEFAULT_PASSWORD = (
    os.getenv("AUTH_DEFAULT_PASSWORD") or "admin123"
).strip() or "admin123"
try:
    AUTH_SESSION_DAYS = int(os.getenv("AUTH_SESSION_DAYS") or "14")
except ValueError:
    AUTH_SESSION_DAYS = 14

_clients_override = (os.getenv("CLIENTS_DATA_DIR") or "").strip()
_mongo_cache_override = (os.getenv("MONGODB_CACHE_DIR") or "").strip()
if MONGODB_URI:
    # Never hydrate over the repository's seed data. Mongo uses an isolated cache.
    CLIENTS_DIR = Path(
        _mongo_cache_override
        or (Path(tempfile.gettempdir()) / f"contentflow-clients-{MONGODB_DB}")
    ).resolve()
elif _clients_override:
    _clients_path = Path(_clients_override)
    if not _clients_path.is_absolute():
        _clients_path = (REPO_ROOT / _clients_path).resolve()
    CLIENTS_DIR = _clients_path
else:
    CLIENTS_DIR = REPO_ROOT / "clients"

# OpenAI / Figma keys are not used by the article-only pipeline (removed).

# Perplexity Sonar (optional — serp / ATP / PAA steps use manual placeholder if unset)
PERPLEXITY_API_KEY = (os.getenv("PERPLEXITY_API_KEY") or "").strip() or None
PERPLEXITY_MODEL = (os.getenv("PERPLEXITY_MODEL") or "sonar").strip() or "sonar"
PERPLEXITY_API_URL = (
    os.getenv("PERPLEXITY_API_URL") or "https://api.perplexity.ai/v1/sonar"
).strip()
try:
    PERPLEXITY_MAX_TOKENS = int(os.getenv("PERPLEXITY_MAX_TOKENS") or "2500")
except ValueError:
    PERPLEXITY_MAX_TOKENS = 2500
try:
    PERPLEXITY_TEMPERATURE = float(os.getenv("PERPLEXITY_TEMPERATURE") or "0.15")
except ValueError:
    PERPLEXITY_TEMPERATURE = 0.15

# Hard quality gates on draft / final (lede, WC, keyword, audit, FAQ).
HARD_GATES_ENABLED = (os.getenv("HARD_GATES_ENABLED") or "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
HARD_GATES_STRICT = (os.getenv("HARD_GATES_STRICT") or "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _env_flag(name: str, default: str = "1") -> bool:
    return (os.getenv(name) or default).strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name) or default))
    except ValueError:
        return default


# Language used when neither the article form nor the topic says otherwise.
DEFAULT_ARTICLE_LANGUAGE = (os.getenv("DEFAULT_ARTICLE_LANGUAGE") or "en").strip().lower() or "en"

# French quality layer (only runs for French articles).
#   FRENCH_QA_ENABLED       English words / banned words / placeholders / brand terms
#   FRENCH_SPELLCHECK       French spelling check (needs `pyspellchecker`)
#   FRENCH_FAQ_LLM_CHECK    ask the model whether each FAQ answer is French AND answers its question
FRENCH_QA_ENABLED = _env_flag("FRENCH_QA_ENABLED")
FRENCH_SPELLCHECK_ENABLED = _env_flag("FRENCH_SPELLCHECK")
FRENCH_FAQ_LLM_CHECK = _env_flag("FRENCH_FAQ_LLM_CHECK")

# Retries instead of fallback text: how many times a failed quality check regenerates.
QUALITY_RETRY_ATTEMPTS = _env_int("QUALITY_RETRY_ATTEMPTS", 3)
# Claude API call attempts (network / provider errors).
CLAUDE_MAX_ATTEMPTS = _env_int("CLAUDE_MAX_ATTEMPTS", 3, minimum=1)

STEP_CONTEXT_FILES = {
    "topic_card": ["context.md"],
    "serp_research": [],
    "research": ["context.md", "personas.md"],
    "source_research": ["context.md"],
    # Internal sub-artifacts (written inside source_research / draft; not UI steps).
    "atp_topic_research": [],
    "paa_faq_research": [],
    "case_study_research": [],
    "research_audit": ["context.md"],
    "assignment_brief": ["context.md", "personas.md"],
    "outline": ["context.md", "personas.md"],
    "draft": ["context.md", "personas.md", "brand_voice.md", "writing_guidelines.md"],
    "supporting_posts": [
        "context.md",
        "personas.md",
        "brand_voice.md",
        "writing_guidelines.md",
    ],
    "fact_check": [],
    "final_output": ["cta_guidelines.md", "internal_links.md"],
    "meta_seo": ["context.md"],
    # Read by the French quality layer (not appended to step prompts as a raw file).
    "french_glossary": ["french_glossary.md"],
}

CONTEXT_FILE_LABELS: dict[str, str] = {
    "french_glossary.md": "Glossaire français (termes de marque, mots interdits)",
    "context.md": "Company / product context",
    "personas.md": "Audience personas",
    "brand_voice.md": "Brand voice",
    "writing_guidelines.md": "Writing guidelines",
    "cta_guidelines.md": "CTA guidelines (tone, URL, optional HTML template)",
    "internal_links.md": "Internal linking & clusters",
}


def pipeline_context_filenames_ordered() -> list[str]:
    """Stable union of STEP_CONTEXT_FILES in pipeline step declaration order."""
    out: list[str] = []
    seen: set[str] = set()
    for filenames in STEP_CONTEXT_FILES.values():
        for fn in filenames:
            if fn not in seen:
                seen.add(fn)
                out.append(fn)
    return out


CONTEXT_FILES_CATALOG: list[dict[str, str]] = [
    {"filename": fn, "label": CONTEXT_FILE_LABELS.get(fn, fn)}
    for fn in pipeline_context_filenames_ordered()
]


def ensure_dirs():
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)


ensure_dirs()
