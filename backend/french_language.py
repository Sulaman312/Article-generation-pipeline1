"""French-only quality layer: prompt rules, glossary, and a deterministic text scanner.

Three jobs live here so the rest of the pipeline stays small:

1. **Prompt blocks written in French** (`system_block`, `step_directive`) with the
   one rule ``FRENCH_RULE``, a banned-word list with French replacements, and the
   brand glossary (« formule Découverte / Énergie / Gagnant »).
2. **Glossary parsing** from the optional workspace file ``french_glossary.md``
   (falls back to the defaults below when the file does not exist).
3. **A scanner** (`scan_french`) that finds English words, banned words, brand-term
   variants, placeholders and French spelling errors. Hard gates, the brief/outline/
   meta checks and the pre-publish check all use it.

Nothing here inserts default text. When the scanner finds problems the caller
retries the generation (see `enforce_french_artifact`) or blocks.
"""

from __future__ import annotations

import html as _html
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

logger = logging.getLogger(__name__)

FRENCH_RULE = (
    "Tout en français, aucun mot anglais, y compris titres, FAQ, tableaux et méta."
)

GLOSSARY_FILENAME = "french_glossary.md"
GLOSSARY_LABEL = "Glossaire français (termes de marque, mots interdits)"

# ---------------------------------------------------------------------------
# Defaults (overridable per workspace through french_glossary.md)
# ---------------------------------------------------------------------------

# English word or phrase  ->  French replacement.
DEFAULT_BANNED: dict[str, str] = {
    "bowl": "bol",
    "wrap": "galette roulée",
    "snack": "collation",
    "pack": "formule",
    "coaching": "accompagnement",
    "coach": "accompagnateur",
    "batch cooking": "préparation des repas à l'avance",
    "meal prep": "préparation des repas",
    "meal": "repas",
    "lunch": "déjeuner",
    "lunchbox": "boîte-repas",
    "dinner": "dîner",
    "breakfast": "petit-déjeuner",
    "brunch": "repas tardif du matin",
    "takeaway": "plat à emporter",
    "topping": "garniture",
    "dressing": "vinaigrette",
    "healthy": "sain",
    "fresh": "frais",
    "fitness": "remise en forme",
    "workout": "séance d'entraînement",
    "tips": "conseils",
    "tip": "conseil",
    "recipe": "recette",
    "delivery": "livraison",
    "subscription": "abonnement",
    "box": "boîte",
    "vegan": "végétalien",
    "gluten free": "sans gluten",
    "low carb": "pauvre en glucides",
    "high protein": "riche en protéines",
    "protein": "protéine",
    "lifestyle": "mode de vie",
    "feedback": "retour",
    "deadline": "échéance",
    "meeting": "réunion",
    "mindset": "état d'esprit",
    "boost": "coup de pouce",
    "cluster": "regroupement thématique",
    "tag": "étiquette",
    "swap": "remplacement",
    "hook": "accroche",
    "snippet": "extrait",
    "workflow": "processus",
    "insight": "enseignement",
    "landing page": "page d'atterrissage",
    "key takeaways": "à retenir",
    "table of contents": "sommaire",
    "table of content": "sommaire",
}

# Brand terms the model must use exactly as written (and never rename).
DEFAULT_BRAND_TERMS: tuple[str, ...] = (
    "formule Découverte",
    "formule Énergie",
    "formule Gagnant",
)

# Words a model likes to swap in for « formule » when it forgets the glossary.
_BRAND_ALT_NOUNS = (
    "pack",
    "offre",
    "forfait",
    "menu",
    "box",
    "kit",
    "programme",
    "pass",
    "abonnement",
    "plan",
)

# Foreign words that are accepted as-is in French copy (food and culture terms the
# dictionaries often miss). Extend per workspace in french_glossary.md.
DEFAULT_ALLOWED: frozenset[str] = frozenset(
    {
        "quinoa", "tofu", "houmous", "hummus", "wasabi", "sushi", "pizza", "curry",
        "kiwi", "pesto", "falafel", "kebab", "tahini", "tempeh", "seitan", "miso",
        "matcha", "granola", "muesli", "ketchup", "yaourt", "boulgour", "brocoli",
        "brocolis", "edamame", "guacamole", "tzatziki", "taboulé", "tajine",
        "seo", "faq", "url", "html", "pdf", "web", "email", "e-mail", "wifi",
        "week-end", "marketing", "blog", "internet", "site", "newsletter",
    }
)

# ---------------------------------------------------------------------------
# English words that are NOT French words (curated; the dictionaries we use for
# spelling happen to contain many English words, so they cannot be trusted here).
# ---------------------------------------------------------------------------

_ENGLISH_ONLY_WORDS = """
the and with your you yours for from this that these those are was were been being
have has had having will would could should can cannot may might shall what when where
why how which who whom whose their theirs there here they them its his hers himself
herself itself not also just only more most much many some any all each every other
another such than then into onto over under about above below after before between
through during without within because while until again very really too own same both
either neither whether although though however therefore thus yet still already even
ever never always often sometimes maybe perhaps once twice of to at by is it be we
get gets getting make makes making take takes taking use uses using used need needs
want wants find finds learn learns read reads click clicks start starts started
starting try tries trying keep keeps help helps helping give gives know knows think
thinks look looks show shows tell tells ask asks work works working build builds
building choose chooses create creates share subscribe download order orders ordering
best better good great easy quick fast fresh healthy daily weekly monthly today
tomorrow yesterday new free top ultimate complete essential perfect tasty delicious
homemade balanced light full
tips tip recipe recipes meal meals lunch dinner breakfast brunch snack snacks bowl
bowls wrap wraps pack packs coaching coach coaches batch cooking prep topping toppings
dressing takeaway delivery subscription box boxes fitness workout workouts program
programs cluster clusters tag tags swap swaps feedback deadline meeting mindset boost
goal goals team customer customers weight loss diet protein proteins carb carbs fiber
benefits benefit results lifestyle journey website online offline contents takeaways
key low high
january february march april june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
""".split()

ENGLISH_ONLY: frozenset[str] = frozenset(_ENGLISH_ONLY_WORDS)

# Dates and labels that show up when a template is not localised.
_ENGLISH_DATE_ABBR = re.compile(
    r"(?<![\w])(?:Jan|Feb|Apr|Aug|Sep|Sept|Dec)\.(?!\w)"
)

# ---------------------------------------------------------------------------
# Placeholders and legacy fallback text that must never be published
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "marqueur [INSERT/VERIFY/TODO…]",
        re.compile(
            r"\[\s*(?:insert|verify|todo|tbd|draft\s+note|placeholder|citation\s+needed|"
            r"xxx|à\s+compléter|a\s+completer)\b[^\]]*\]",
            re.I,
        ),
    ),
    (
        "texte de remplacement entre crochets",
        re.compile(
            r"\[\s*(?:not\s+available\s+yet|none|not\s+yet\s+provided|not\s+provided|"
            r"missing|draft\s+missing|outline\s+missing|perplexity[^\]]*|"
            r"…\s*excerpt\s+truncated\s*…)\s*\]",
            re.I,
        ),
    ),
    ("variable {{…}} non remplacée", re.compile(r"\{\{[^}]*\}\}")),
    ("lorem ipsum", re.compile(r"lorem\s+ipsum", re.I)),
    ("TODO / TBD", re.compile(r"(?<![\w-])(?:TODO|TBD|XXX)(?![\w-])")),
    ("points de suspension entre crochets", re.compile(r"\[\s*(?:\.{3}|…)\s*\]")),
    (
        "ancien texte par défaut (FAQ)",
        re.compile(
            r"it depends on (?:the task|your situation)|"
            r"cela dépend de votre situation, de vos contraintes et de ce que vous "
            r"pouvez préparer d['’]abord|"
            r"commencez par une étape claire avec un résultat simple à vérifier|"
            r"ajustez ensuite selon ce résultat avant d['’]élargir|"
            r"start with one clear (?:step|job)|"
            r"review the result before you widen",
            re.I,
        ),
    ),
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Glossary:
    banned: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BANNED))
    brand_terms: list[str] = field(default_factory=lambda: list(DEFAULT_BRAND_TERMS))
    allowed: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED))


@dataclass(frozen=True)
class FrenchIssue:
    code: str  # fr_english_word | fr_banned_word | fr_brand_term | fr_placeholder | fr_spelling
    term: str
    suggestion: str = ""
    context: str = ""
    count: int = 1

    def message(self) -> str:
        where = f' (ex. : « {self.context} »)' if self.context else ""
        n = f" ×{self.count}" if self.count > 1 else ""
        if self.code == "fr_english_word":
            tip = f" Remplacez-le par un mot français{': « ' + self.suggestion + ' »' if self.suggestion else ''}."
            return f"Mot anglais « {self.term} »{n}.{tip}{where}"
        if self.code == "fr_banned_word":
            return (
                f"Mot interdit « {self.term} »{n} : écrivez « {self.suggestion} ».{where}"
            )
        if self.code == "fr_brand_term":
            return (
                f"Terme de marque incorrect « {self.term} »{n} : utilisez exactement "
                f"« {self.suggestion} ».{where}"
            )
        if self.code == "fr_placeholder":
            return f"Texte provisoire ou par défaut : {self.term}{n}. Réécrivez un vrai contenu.{where}"
        if self.code == "fr_spelling":
            tip = f" Correction probable : « {self.suggestion} »." if self.suggestion else ""
            return f"Faute d'orthographe « {self.term} »{n}.{tip}{where}"
        return f"{self.term}{n}{where}"


class FrenchQualityError(RuntimeError):
    """Raised when French checks still fail after every retry."""

    def __init__(self, label: str, issues: list[FrenchIssue]):
        self.label = label
        self.issues = issues
        super().__init__(format_issues(issues, header=f"{label} : contrôle de français échoué"))


def format_issues(issues: list[FrenchIssue], *, header: str = "", limit: int = 40) -> str:
    lines = [header] if header else []
    for issue in issues[:limit]:
        lines.append(f"- {issue.message()}")
    if len(issues) > limit:
        lines.append(f"- … et {len(issues) - limit} autre(s) problème(s).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Glossary file
# ---------------------------------------------------------------------------

_ARROW = re.compile(r"\s*(?:→|->|=>|=|:)\s*")


def _clean_term(raw: str) -> str:
    return raw.strip().strip("«»\"“”'`").strip()


def parse_glossary(text: str | None) -> Glossary:
    """Merge ``french_glossary.md`` into the defaults.

    Recognised sections (heading words are enough, any ``#`` level)::

        ## Termes de la marque        -> "- formule Découverte"
        ## Mots interdits             -> "- bowl → bol"
        ## Mots autorisés             -> "- NomPropre"
    """
    glossary = Glossary()
    if not (text or "").strip():
        return glossary

    brand: list[str] = []
    banned: dict[str, str] = {}
    allowed: set[str] = set()
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            low = line.lower()
            if "marque" in low or "brand" in low:
                section = "brand"
            elif "interdit" in low or "banni" in low or "banned" in low:
                section = "banned"
            elif "autoris" in low or "allowed" in low:
                section = "allowed"
            else:
                section = ""
            continue
        item = re.sub(r"^[-*•]\s+", "", line)
        if not item or not section:
            continue
        if section == "brand":
            term = _clean_term(item)
            if term:
                brand.append(term)
        elif section == "banned":
            parts = _ARROW.split(item, maxsplit=1)
            if len(parts) == 2:
                en, fr = _clean_term(parts[0]).lower(), _clean_term(parts[1])
                if en and fr:
                    banned[en] = fr
        elif section == "allowed":
            for piece in re.split(r"[,;]", item):
                word = _clean_term(piece).lower()
                if word:
                    allowed.add(word)

    if brand:
        glossary.brand_terms = brand
    glossary.banned.update(banned)
    glossary.allowed |= allowed
    return glossary


def load_glossary(client_id: str | None) -> Glossary:
    """Workspace glossary, or the defaults when the file does not exist."""
    if not client_id:
        return Glossary()
    try:
        from . import artifacts

        text = artifacts.read_context_file(client_id, GLOSSARY_FILENAME)
    except Exception:  # unknown file name, storage error: defaults are safe
        logger.debug("french glossary not readable for %s", client_id, exc_info=True)
        text = None
    return parse_glossary(text)


GLOSSARY_PLACEHOLDER = (
    "# Glossaire français\n\n"
    "## Termes de la marque\n"
    "- formule Découverte\n"
    "- formule Énergie\n"
    "- formule Gagnant\n\n"
    "## Mots interdits\n"
    "- bowl → bol\n"
    "- wrap → galette roulée\n"
    "- snack → collation\n"
    "- pack → formule\n"
    "- coaching → accompagnement\n"
    "- batch cooking → préparation des repas à l'avance\n\n"
    "## Mots autorisés\n"
    "- (noms propres, marques ou termes étrangers acceptés, séparés par des virgules)\n"
)

# ---------------------------------------------------------------------------
# Prompt blocks (written in French)
# ---------------------------------------------------------------------------


def _banned_lines(glossary: Glossary, limit: int = 60) -> str:
    return "\n".join(
        f"- {en} → {fr}" for en, fr in list(glossary.banned.items())[:limit]
    )


def _brand_lines(glossary: Glossary) -> str:
    return "\n".join(f"- « {t} »" for t in glossary.brand_terms)


def system_block(glossary: Glossary | None = None) -> str:
    """Top-of-system French rule block (used for every step of a French run)."""
    g = glossary or Glossary()
    first_brand = g.brand_terms[0] if g.brand_terms else "formule Découverte"
    return (
        "=== RÈGLE DE LANGUE (PRIORITAIRE ET NON NÉGOCIABLE) ===\n"
        f"{FRENCH_RULE}\n\n"
        "Cette règle couvre tout ce que vous écrivez : titre H1, intertitres, listes, "
        "tableaux (en-têtes et cellules), FAQ (questions et réponses), légendes et "
        "textes alternatifs des images, appels à l'action, titre et description méta, "
        "ainsi que les briefs, plans et notes destinés à l'équipe.\n\n"
        "Les documents fournis peuvent contenir des termes anglais (noms de champs, "
        "jargon, titres de concurrents). Ne les recopiez jamais : traduisez ou "
        "reformulez en français. Seuls restent tels quels les noms propres, les noms "
        "de marque, les sigles usuels (SEO, FAQ, URL) et les balises techniques du "
        "format (par exemple ---DRAFT START---, IMAGE:, INTERNAL:), qui ne sont pas "
        "du texte lu par le lecteur.\n"
        "Les listes de mots interdits en anglais présentes dans d'autres consignes ne "
        "s'appliquent pas : suivez la liste française ci-dessous.\n\n"
        "MOTS INTERDITS (n'écrivez jamais le mot de gauche, écrivez celui de droite) :\n"
        f"{_banned_lines(g)}\n\n"
        "GLOSSAIRE DE LA MARQUE (employez ces termes exacts, avec cette orthographe et "
        "cette majuscule ; n'en inventez aucun autre) :\n"
        f"{_brand_lines(g)}\n"
        f"N'écrivez jamais « pack », « offre », « forfait » ni « menu » à la place de "
        f"« formule » (par exemple, pas « pack Découverte » : écrivez « {first_brand} »).\n\n"
        "JARGON DANS LES BRIEFS ET LES PLANS : le modèle recopie ce qu'il lit. Écrivez "
        "« regroupement thématique » (pas « cluster »), « étiquette » (pas « tag »), "
        "« remplacement » (pas « swap »), « à retenir » (pas « key takeaways »), "
        "« accroche » (pas « hook »), « page d'atterrissage » (pas « landing page »).\n\n"
        "Si vous n'avez pas assez d'informations pour écrire une partie, reprenez la "
        "recherche fournie ou précisez-le franchement : n'écrivez jamais de texte "
        "générique de remplissage ni de marqueur du type [À COMPLÉTER].\n"
        "=== FIN DE LA RÈGLE DE LANGUE ===\n"
    )


STYLE_RULE = (
    "Style : au moins 30 % des phrases contiennent un connecteur (ainsi, en effet, par "
    "ailleurs, en revanche, donc, toutefois, cependant, ensuite, enfin, par exemple, car), "
    "mais jamais « de plus », que Yoast ne reconnaît pas. Ne commencez jamais trois "
    "phrases de suite par le même mot. Texte alternatif de chaque image : une phrase "
    "descriptive de 8 à 15 mots, sans trait d'union ni tiret. Exactement deux appels à "
    "l'action : un entre deux sections, un à la fin, aucun au début de l'article."
)

_STEP_DIRECTIVES: dict[str, str] = {
    "topic_card": (
        "Fiche sujet : écrivez les valeurs en français. Les étiquettes de champs en "
        "majuscules restent inchangées car le système les lit."
    ),
    "assignment_brief": (
        "Brief : rédigez tout en français, y compris les consignes au rédacteur. Les "
        "étiquettes de champs en MAJUSCULES (ARTICLE TITLE, PRIMARY KEYWORD…) restent "
        "identiques car le système les lit, mais tout ce qui suit les deux-points est "
        "en français : titres, intertitres proposés, thème de la FAQ, ton, notes. "
        "Aucun jargon anglais (cluster, tag, swap, key takeaways, hook…)."
    ),
    "outline": (
        "Plan : intertitres, notes de section, plan de la FAQ et consignes d'images "
        "entièrement en français. Les étiquettes en MAJUSCULES restent inchangées. "
        "Aucun jargon anglais."
    ),
    "draft": (
        "Brouillon : article 100 % français. Titre, intertitres (« À retenir », "
        "« Questions fréquentes »), tableaux, FAQ, textes alternatifs des images et "
        "appels à l'action en français. Chaque réponse de FAQ répond réellement à sa "
        "question, en 2 à 4 phrases françaises. Utilisez les termes exacts du glossaire. "
        + STYLE_RULE
    ),
    "supporting_posts": (
        "Articles satellites : 100 % français, mêmes règles que l'article principal "
        "(titres, tableaux, FAQ, méta). Termes de marque exacts."
    ),
    "fact_check": (
        "Vérification : l'article corrigé reste 100 % français. Corrigez aussi tout mot "
        "anglais, mot interdit ou terme de marque incorrect que vous rencontrez. Le "
        "rapport de vérification est lui aussi rédigé en français."
    ),
    "final_output": (
        "Version finale : article 100 % français, y compris appels à l'action, légendes, "
        "tableaux et FAQ. Corrigez au passage tout mot anglais ou mot interdit restant. "
        "Chaque réponse de FAQ doit répondre à sa question. "
        + STYLE_RULE
    ),
    "meta_seo": (
        "Méta : titres et descriptions méta 100 % en français, sans mot anglais, avec "
        "les termes de marque exacts."
    ),
    "research_audit": (
        "Audit : rédigez les décisions et les questions de FAQ approuvées en français."
    ),
    "research": "Analyse : rédigez les synthèses et recommandations en français.",
}


def step_directive(step_name: str, glossary: Glossary | None = None) -> str:
    """Short French reminder appended after the step prompt (most recent instruction)."""
    g = glossary or Glossary()
    specific = _STEP_DIRECTIVES.get(step_name, "")
    brand = " / ".join(g.brand_terms) if g.brand_terms else ""
    lines = [f"=== RAPPEL : LANGUE FRANÇAISE ===", FRENCH_RULE]
    if specific:
        lines.append(specific)
    if brand:
        lines.append(f"Termes de marque exacts : {brand}.")
    lines.append(
        "Relisez avant de répondre : aucun mot anglais, aucun mot de la liste des mots "
        "interdits, aucun texte provisoire."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b[\s\S]*?</\1>", re.I)
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_HTML_TAG = re.compile(r"<[^>]+>")
_STEP_MARKER = re.compile(r"^\s*-{3}[A-Z0-9 ()/\-]+-{3}\s*$", re.M)
_LABEL_PREFIX = re.compile(r"^(\s*(?:[-*]\s+)?)[A-Z][A-Z0-9 /&\-]{2,}:\s*", re.M)
_H_LABEL = re.compile(r"^(\s*(?:[-*]\s+)?)H[1-6]:\s*", re.M)
_MD_IMAGE_TARGET = re.compile(r"(!\[[^\]]*\])\([^)]*\)")
_MD_LINK_TARGET = re.compile(r"(\[[^\]]*\])\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*(?:-[^\W\d_]+)*", re.UNICODE)
_SENTENCE_END = set(".!?\n#|>*-:")

_VERB_ENDINGS = ("ez", "ons", "ent", "ais", "ait", "ions", "iez", "aient", "ant")


def prose_for_scan(text: str, *, structural: bool = False) -> str:
    """Reduce markdown/HTML to the words a reader would see.

    Keeps headings, table cells, FAQ, link anchors and image alt text. Drops URLs,
    link/image targets, code fences, scripts, pipeline markers, and (for briefs and
    outlines) the upper-case field labels the system parses.
    """
    t = text or ""
    t = _SCRIPT_STYLE.sub(" ", t)
    t = _HTML_COMMENT.sub(" ", t)
    t = _CODE_FENCE.sub(" ", t)
    t = _STEP_MARKER.sub(" ", t)
    t = _MD_IMAGE_TARGET.sub(r"\1", t)
    t = _MD_LINK_TARGET.sub(r"\1", t)
    t = re.sub(r"</?(?:p|div|br|li|tr|h[1-6]|table|ul|ol|section|article)\b[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = _HTML_TAG.sub(" ", t)
    t = _html.unescape(t)
    t = _EMAIL.sub(" ", t)
    t = _BARE_URL.sub(" ", t)
    if structural:
        t = _H_LABEL.sub(r"\1", t)
        t = _LABEL_PREFIX.sub(r"\1", t)
    return t


def _strip_accents(word: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn"
    )


@lru_cache(maxsize=1)
def _spellcheckers():
    try:
        from spellchecker import SpellChecker
    except ImportError:
        logger.warning(
            "pyspellchecker is not installed: French spelling check is OFF. "
            "Run: pip install -r requirements.txt"
        )
        return None, None
    return SpellChecker(language="fr"), SpellChecker(language="en")


def spellcheck_available() -> bool:
    return _spellcheckers()[0] is not None


def _context(text: str, start: int, end: int, radius: int = 28) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = re.sub(r"\s+", " ", text[left:right]).strip()
    return ("…" if left else "") + snippet + ("…" if right < len(text) else "")


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in re.split(r"[\s\-]+", phrase.strip()) if w]
    body = r"[\s\-]+".join(words)
    plural = "" if phrase.strip().endswith("s") else "(?:s|x)?"
    return re.compile(rf"(?<![\w]){body}{plural}(?![\w])", re.I)


def _scan_banned(text: str, glossary: Glossary) -> tuple[list[FrenchIssue], list[tuple[int, int]]]:
    issues: list[FrenchIssue] = []
    spans: list[tuple[int, int]] = []
    # Longest phrases first so « batch cooking » wins over « batch ».
    for en in sorted(glossary.banned, key=len, reverse=True):
        fr = glossary.banned[en]
        matches = [
            m
            for m in _phrase_pattern(en).finditer(text)
            if not any(s <= m.start() < e for s, e in spans)
        ]
        if not matches:
            continue
        if en.lower() in glossary.allowed:
            continue
        for m in matches:
            spans.append((m.start(), m.end()))
        first = matches[0]
        issues.append(
            FrenchIssue(
                "fr_banned_word",
                en,
                fr,
                _context(text, first.start(), first.end()),
                len(matches),
            )
        )
    return issues, spans


def _scan_brand_terms(text: str, glossary: Glossary) -> list[FrenchIssue]:
    issues: list[FrenchIssue] = []
    for term in glossary.brand_terms:
        parts = term.split(None, 1)
        if len(parts) != 2:
            continue
        prefix, name = parts
        # 1) Same words, wrong capitalisation (« formule découverte », « Formule Découverte » mid-sentence).
        for m in re.finditer(
            rf"(?<!\w){re.escape(prefix)}\s+{re.escape(name)}(?!\w)", text, re.I
        ):
            found = re.sub(r"\s+", " ", m.group(0))
            sentence_start = m.start() == 0 or text[:m.start()].rstrip()[-1:] in ".!?\n#*-|>:"
            ok = found == term or (
                sentence_start and found[0].upper() + found[1:] == found
                and found[0].lower() + found[1:] == term
            )
            if not ok:
                issues.append(
                    FrenchIssue(
                        "fr_brand_term",
                        found,
                        term,
                        _context(text, m.start(), m.end()),
                    )
                )
        # 2) Another noun in front of the brand name (« pack Découverte »).
        alt = "|".join(_BRAND_ALT_NOUNS)
        for m in re.finditer(
            rf"(?<!\w)(?:{alt})s?\s+{re.escape(name)}(?!\w)", text, re.I
        ):
            issues.append(
                FrenchIssue(
                    "fr_brand_term",
                    re.sub(r"\s+", " ", m.group(0)),
                    term,
                    _context(text, m.start(), m.end()),
                )
            )
    return issues


def _scan_placeholders(raw_text: str, text: str) -> list[FrenchIssue]:
    issues: list[FrenchIssue] = []
    seen: set[str] = set()
    for label, pattern in _PLACEHOLDER_PATTERNS:
        for source in (raw_text, text):
            m = pattern.search(source or "")
            if m and label not in seen:
                seen.add(label)
                issues.append(
                    FrenchIssue(
                        "fr_placeholder",
                        label,
                        "",
                        _context(source, m.start(), m.end()),
                        len(pattern.findall(source)),
                    )
                )
                break
    return issues


# Words cut by an apostrophe (jusqu'à, lorsqu'il, aujourd'hui) are not words on their own.
_ELISION_STEMS = frozenset(
    {"jusqu", "lorsqu", "puisqu", "quelqu", "presqu", "quoiqu", "aujourd", "prud"}
)


def _is_name_position(text: str, start: int, token: str) -> bool:
    """True for a capitalised word in the middle of a sentence (likely a proper noun)."""
    if not token[:1].isupper() or token.isupper():
        return False
    i = start - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    return i >= 0 and text[i] not in _SENTENCE_END


def scan_french(
    text: str,
    *,
    glossary: Glossary | None = None,
    spelling: bool = True,
    english: bool = True,
    banned: bool = True,
    placeholders: bool = True,
    structural: bool = False,
) -> list[FrenchIssue]:
    """Scan French copy. Returns issues; an empty list means the text is clean."""
    g = glossary or Glossary()
    raw = text or ""
    if not raw.strip():
        return []
    prose = prose_for_scan(raw, structural=structural)
    issues: list[FrenchIssue] = []
    spans: list[tuple[int, int]] = []

    if placeholders:
        issues.extend(_scan_placeholders(raw, prose))
    if banned:
        banned_issues, spans = _scan_banned(prose, g)
        issues.extend(banned_issues)
        issues.extend(_scan_brand_terms(prose, g))

    allowed = {w.lower() for w in g.allowed}
    fr_spell, en_spell = _spellcheckers() if (spelling or english) else (None, None)

    english_hits: dict[str, list[int]] = {}
    for m in _ENGLISH_DATE_ABBR.finditer(prose):
        if english:
            issues.append(
                FrenchIssue(
                    "fr_english_word",
                    m.group(0),
                    "sept., oct., janv., févr., avr., août, déc. (abréviations françaises)",
                    _context(prose, m.start(), m.end()),
                )
            )

    spell_candidates: dict[str, list[tuple[int, str]]] = {}
    for m in _TOKEN.finditer(prose):
        token = m.group(0)
        start = m.start()
        if any(s <= start < e for s, e in spans):
            continue
        low = token.lower().replace("’", "'")
        if low in allowed or token.isupper():
            continue
        parts = [p for p in re.split(r"['\-]", low) if p]
        if english:
            hit = next((p for p in parts if p in ENGLISH_ONLY and p not in allowed), None)
            if hit is None and low in ENGLISH_ONLY:
                hit = low
            if hit is not None:
                english_hits.setdefault(hit, []).append(start)
                continue
        for part in parts:
            if len(part) < 4 or part in allowed or part in _ELISION_STEMS:
                continue
            if _is_name_position(prose, start, token):
                continue
            spell_candidates.setdefault(part, []).append((start, token))

    for word, starts in english_hits.items():
        first = starts[0]
        issues.append(
            FrenchIssue(
                "fr_english_word",
                word,
                g.banned.get(word, ""),
                _context(prose, first, first + len(word)),
                len(starts),
            )
        )

    if (spelling or english) and fr_spell is not None and spell_candidates:
        words = list(spell_candidates)
        unknown = fr_spell.unknown(words)
        for word in sorted(unknown):
            positions = spell_candidates[word]
            first = positions[0][0]
            # A second layer for English words missing from the curated list: unknown
            # in French but a common English word.
            if english and en_spell is not None and word not in g.banned:
                en_freq = en_spell.word_usage_frequency(word)
                if en_freq * 1e6 >= 20 and en_spell.known([word]):
                    issues.append(
                        FrenchIssue(
                            "fr_english_word",
                            word,
                            "",
                            _context(prose, first, first + len(word)),
                            len(positions),
                        )
                    )
                    continue
            if not spelling:
                continue
            suggestion = _spelling_suggestion(fr_spell, word)
            if suggestion:
                issues.append(
                    FrenchIssue(
                        "fr_spelling",
                        word,
                        suggestion,
                        _context(prose, first, first + len(word)),
                        len(positions),
                    )
                )
    return issues


def _spelling_suggestion(fr_spell, word: str) -> str:
    """A confident correction, or '' (unknown words without one are not reported).

    Precision matters more than recall: a false alarm blocks an article. We only
    report (a) missing/wrong accents on a known word and (b) one-letter typos of a
    clearly common word.
    """
    try:
        near = fr_spell.edit_distance_1(word)
    except Exception:  # pragma: no cover - library internals
        return ""
    known = [c for c in fr_spell.known(near) if c != word]
    if not known:
        return ""
    stripped = _strip_accents(word)
    accent_variants = [c for c in known if _strip_accents(c) == stripped]
    pool = accent_variants or known
    best = max(pool, key=lambda c: fr_spell.word_usage_frequency(c))
    freq = fr_spell.word_usage_frequency(best) * 1e6
    if accent_variants:
        return best if freq >= 0.1 else ""
    if word.endswith(_VERB_ENDINGS):
        return ""
    return best if freq >= 2.0 else ""


# ---------------------------------------------------------------------------
# Retry loop (no default text: regenerate, then fail loudly)
# ---------------------------------------------------------------------------


def repair_system_prompt(glossary: Glossary) -> str:
    return (
        "Vous êtes un correcteur éditorial francophone. Corrigez UNIQUEMENT les "
        "problèmes listés par l'utilisateur.\n"
        f"{FRENCH_RULE}\n"
        "Conservez la structure, les titres, les liens (adresses et ancres), les "
        "balises techniques (---…---, IMAGE:, INTERNAL:), les chiffres et le sens. "
        "N'ajoutez aucun texte générique de remplissage.\n"
        "Ne traduisez pas les noms propres ni les noms de marque.\n"
        "Termes de marque exacts : "
        + (" / ".join(glossary.brand_terms) or "(aucun)")
        + ".\n"
        "Mots interdits et remplacements :\n"
        + _banned_lines(glossary)
        + "\nRenvoyez uniquement le document complet corrigé, sans préambule."
    )


def repair_french_llm(
    text: str,
    issues: list[FrenchIssue],
    *,
    step_label: str,
    glossary: Glossary,
    max_tokens: int = 8192,
) -> str:
    from .integrations import anthropic as claude

    user = (
        "Corrigez ces problèmes de langue :\n"
        f"{format_issues(issues, limit=60)}\n\n"
        "---DOCUMENT---\n"
        f"{text.strip()}\n"
        "---FIN DU DOCUMENT---"
    )
    return claude.chat_complete(
        repair_system_prompt(glossary),
        user,
        step_label=f"{step_label} (correction du français)",
        max_tokens=max_tokens,
        temperature=0.2,
    ).strip()


def enforce_french_artifact(
    text: str,
    *,
    step_label: str,
    glossary: Glossary | None = None,
    spelling: bool = False,
    structural: bool = True,
    attempts: int = 3,
    repair: Callable[[str, list[FrenchIssue]], str] | None = None,
) -> str:
    """Scan; on problems ask the model to fix them and re-scan. Raise if still dirty."""
    g = glossary or Glossary()
    current = text
    issues: list[FrenchIssue] = []
    for attempt in range(attempts + 1):
        issues = scan_french(current, glossary=g, spelling=spelling, structural=structural)
        if not issues:
            if attempt:
                logger.info("%s: French check passed after %s repair(s)", step_label, attempt)
            return current
        if attempt == attempts:
            break
        logger.warning(
            "%s: French check found %s issue(s) (attempt %s/%s): %s",
            step_label,
            len(issues),
            attempt + 1,
            attempts,
            "; ".join(i.message() for i in issues[:5]),
        )
        fixer = repair or (
            lambda body, found: repair_french_llm(
                body, found, step_label=step_label, glossary=g
            )
        )
        repaired = fixer(current, issues)
        if repaired and repaired.strip():
            current = repaired
    raise FrenchQualityError(step_label, issues)


__all__ = [
    "FRENCH_RULE",
    "GLOSSARY_FILENAME",
    "GLOSSARY_LABEL",
    "GLOSSARY_PLACEHOLDER",
    "Glossary",
    "FrenchIssue",
    "FrenchQualityError",
    "enforce_french_artifact",
    "format_issues",
    "load_glossary",
    "parse_glossary",
    "prose_for_scan",
    "scan_french",
    "spellcheck_available",
    "step_directive",
    "system_block",
]
