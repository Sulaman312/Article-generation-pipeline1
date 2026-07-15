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
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
CLAUDE_MODEL = (os.getenv("CLAUDE_MODEL") or "claude-sonnet-4-6").strip()
MAX_TOKENS = 4000
TEMPERATURE = 0.7

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

# Perplexity Sonar (optional — Step `serp_research` uses manual placeholder if unset)
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

STEP_CONTEXT_FILES = {
    "topic_card": ["context.md"],
    "serp_research": [],
    "research": ["context.md", "personas.md"],
    "assignment_brief": ["context.md", "personas.md"],
    "outline": ["context.md", "personas.md"],
    "draft": ["context.md", "personas.md", "brand_voice.md", "writing_guidelines.md"],
    "fact_check": [],
    "final_output": ["cta_guidelines.md", "internal_links.md"],
    "meta_seo": ["context.md"],
}

CONTEXT_FILE_LABELS: dict[str, str] = {
    "context.md": "Company / product context",
    "personas.md": "Audience personas",
    "brand_voice.md": "Brand voice",
    "writing_guidelines.md": "Writing guidelines",
    "cta_guidelines.md": "CTA guidelines",
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
