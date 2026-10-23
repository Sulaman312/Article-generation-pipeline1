"""Yoast-aligned transition-word lists for readability (≥30% of sentences).

Lists mirror Yoast SEO language packs (wordpress-seo yoastseo package).
Only these connectors count toward the green bullet — common French words like
``de plus`` are NOT recognized by Yoast and must not be recommended as fixes.
"""

from __future__ import annotations

import re
import unicodedata

# Minimum share of body sentences that must contain a Yoast-recognized connector.
MIN_TRANSITION_RATIO = 0.30

# --- French (Yoast fr/config/transitionWords.js) ---
_FR_SINGLE = (
    "ainsi", "alors", "aussi", "car", "cependant", "certainement", "certes",
    "conséquemment", "d'abord", "d'ailleurs", "d'après", "davantage", "désormais",
    "deuxièmement", "donc", "dorénavant", "effectivement", "également", "enfin",
    "ensuite", "entre-temps", "essentiellement", "excepté", "finalement",
    "globalement", "jusqu'ici", "là-dessus", "lorsque", "mais", "malgré",
    "néanmoins", "notamment", "partant", "plutôt", "pourtant", "précédemment",
    "premièrement", "probablement", "puis", "puisque", "quoique", "sauf",
    "selon", "semblablement", "sinon", "suivant", "toutefois", "troisièmement",
)

_FR_MULTI = (
    "à cause de", "à ce jour", "à ce propos", "à ce sujet", "à cet égard",
    "à cette fin", "à compter de", "à condition que", "à défaut de", "à force de",
    "à juste titre", "à la lumière de", "à la suite de", "à l'aide de",
    "à l'appui de", "à l'encontre de", "à l'époque actuelle", "à l'exception de",
    "à l'exclusion de", "à l'heure actuelle", "à l'image de", "à l'instar de",
    "à l'inverse", "à l'inverse de", "à l'opposé", "à la condition que",
    "à mesure que", "à moins que", "à nouveau", "à partir de", "à première vue",
    "à savoir", "à seule fin que", "à supposer que", "à tel point que",
    "à tout prendre", "à vrai dire", "afin de", "afin que", "ainsi donc",
    "ainsi que", "alors que", "après cela", "après quoi", "après que",
    "à propos de", "après réflexion", "après tout", "attendu que", "au cas où",
    "au contraire", "au fond", "au fur et à mesure", "au lieu de",
    "au même temps", "au moment où", "au moyen de", "au point que",
    "au risque de", "au surplus", "au total", "aussi bien que", "aussitôt que",
    "autant que", "autrement dit", "avant que", "avant tout", "bien que",
    "c'est ainsi que", "c'est dans ce but que", "c'est dire", "c'est le cas de",
    "c'est la raison pour laquelle", "c'est pourquoi", "c'est qu'en effet",
    "c'est-à-dire", "cela étant", "cela dit", "cependant que", "compte tenu",
    "comme l'illustre", "comme le souligne", "comme on pouvait s'y attendre",
    "comme quoi", "comme si", "comparativement à", "conformément à",
    "contrairement à", "considérons par exemple", "d'autant plus", "d'autant que",
    "d'autre part", "d'ici là", "d'où", "d'un autre côté", "d'un côté",
    "d'une façon générale", "dans ce cas", "dans ces conditions", "dans cet esprit",
    "dans l'ensemble", "dans l'état actuel des choses", "dans l'éventualité où",
    "dans l'hypothèse où", "dans la mesure où", "dans le but de",
    "dans le cadre de", "dans le cas où", "dans les circonstances actuelles",
    "dans les grandes lignes", "dans un autre ordre d'idée", "dans un délai de",
    "de ce fait", "de cette façon", "de crainte que", "de façon à",
    "de façon à ce que", "de façon que", "de fait", "de l'autre côté",
    "de la même manière", "de la même façon que", "de manière que", "de même",
    "de même que", "de nos jours", "de peur que", "de prime abord",
    "de sorte que", "de surcroît", "de telle manière que", "de telle sorte que",
    "de toute évidence", "de toute façon", "de toute manière", "depuis que",
    "dès lors que", "dès maintenant", "dès que", "du fait que", "du moins",
    "du moment que", "du point de vue de", "du reste", "d'ores et déjà",
    "en admettant que", "en attendant que", "en bref", "en cas de", "en cas que",
    "en ce cas", "en ce domaine", "en ce moment", "en ce qui a trait à",
    "en ce qui concerne", "en ce sens", "en cela", "en comparaison de",
    "en conclusion", "en conformité avec", "en conséquence", "en d'autres termes",
    "en définitive", "en dépit de", "pour cela", "en dernier lieu",
    "en deuxième lieu", "en effet", "en face de", "en fait", "en fin de compte",
    "en général", "en guise de conclusion", "en matière de", "en même temps que",
    "en outre", "en particulier", "en plus", "en premier lieu", "en principe",
    "en raison de", "en réalité", "en règle générale", "en résumé", "en revanche",
    "en second lieu", "en somme", "en sorte que", "en supposant que",
    "en tant que", "en terminant", "en théorie", "en tout cas",
    "en tout premier lieu", "en troisième lieu", "en un mot", "en vérité",
    "en vue que", "encore que", "encore une fois", "entre autres", "et même",
    "et puis", "étant donné que", "face à", "grâce à", "il est à noter que",
    "il est indéniable que", "il est question de", "il est vrai que",
    "il faut dire aussi que", "il faut reconnaître que", "il faut souligner que",
    "il ne faut pas oublier que", "il s'ensuit que", "il y a aussi",
    "jusqu'à ce que", "jusqu'à ce jour", "jusqu'à maintenant", "jusqu'à présent",
    "jusqu'au moment où", "loin que", "mais en réalité", "malgré cela",
    "malgré tout", "même si", "mentionnons que", "mis à part le fait que",
    "notons que", "nul doute que", "ou bien", "outre cela", "par ailleurs",
    "par conséquent", "par contre", "par exception", "par exemple",
    "par la suite", "par l'entremise de", "par l'intermédiaire de",
    "par rapport à", "par suite", "par suite de", "par surcroît", "parce que",
    "pareillement", "partant de ce fait", "pendant que", "plus précisément",
    "plus tard", "pour ainsi dire", "pour autant que", "pour ce qui est de",
    "pour ces motifs", "pour ces raisons", "pour cette raison", "pour commencer",
    "pour conclure", "pour le moment", "pour l'instant", "pour peu que",
    "pour prendre un autre exemple", "pour que", "pour terminer", "pour tout dire",
    "pour toutes ces raisons", "pourvu que", "prenons le cas de", "quand même",
    "quant à", "quel que soit", "qui plus est", "surtout quand", "quitte à",
    "quoi qu'il en soit", "quoi que", "sans délai", "sans doute", "sans parler de",
    "sans préjuger", "sans tarder", "sauf si", "selon que", "si bien que",
    "si ce n'est que", "si l'on songe que", "sitôt que", "somme toute",
    "sur ce point", "surtout si", "sous cette réserve", "sous prétexte que",
    "sous réserve de", "sous réserve que", "suivant que", "supposé que",
    "sur le plan de", "tandis que", "tant et si bien que", "tant que", "tel que",
    "tellement que", "tout à fait", "tout bien pesé", "tout compte fait",
    "tout d'abord", "tout de même", "tout en reconnaissant que",
    "une fois de plus", "vu que",
)

# Prefer these in FR prompts (common, natural, Yoast-recognized). Avoid "de plus".
FR_PROMPT_EXAMPLES = (
    "en effet", "par exemple", "donc", "ainsi", "ensuite", "enfin", "cependant",
    "toutefois", "en revanche", "par ailleurs", "en outre", "en plus", "car",
    "parce que", "c'est pourquoi", "de ce fait", "par conséquent", "d'abord",
    "puis", "également", "notamment", "autrement dit", "en résumé",
)

# --- English (Yoast en/config/transitionWords.js) — high-value subset for matching ---
_EN_SINGLE = (
    "accordingly", "additionally", "afterward", "afterwards", "albeit", "also",
    "although", "altogether", "basically", "because", "before", "besides", "but",
    "certainly", "chiefly", "comparatively", "concurrently", "consequently",
    "contrarily", "conversely", "correspondingly", "despite", "during", "earlier",
    "equally", "especially", "eventually", "evidently", "explicitly", "finally",
    "firstly", "following", "formerly", "further", "furthermore", "generally",
    "hence", "however", "indeed", "initially", "instead", "last", "lastly",
    "later", "likewise", "meanwhile", "moreover", "nevertheless", "nonetheless",
    "nor", "otherwise", "overall", "particularly", "previously", "rather",
    "regardless", "secondly", "similarly", "simultaneously", "since", "so",
    "specifically", "still", "subsequently", "then", "thereafter", "therefore",
    "thirdly", "though", "thus", "unless", "until", "when", "whenever",
    "whereas", "while", "whether", "if", "actually", "namely", "including",
)

_EN_MULTI = (
    "above all", "after all", "after that", "all in all", "as a matter of fact",
    "as a result", "as an illustration", "as long as", "as soon as", "as well as",
    "at first", "at last", "at least", "at the same time", "by contrast",
    "compared to", "due to", "even if", "even so", "even though", "for example",
    "for instance", "for that reason", "for this reason", "given that",
    "in addition", "in brief", "in conclusion", "in contrast", "in fact",
    "in general", "in other words", "in particular", "in short", "in spite of",
    "in summary", "in that case", "in the meantime", "in this case",
    "on the contrary", "on the other hand", "on the whole", "provided that",
    "so that", "such as", "that is", "that is to say", "then again",
    "to begin with", "to conclude", "to illustrate", "to sum up", "to summarize",
    "what is more", "what's more", "according to",
)

EN_PROMPT_EXAMPLES = (
    "however", "therefore", "for example", "in addition", "also", "next",
    "finally", "meanwhile", "as a result", "because", "so", "first", "then",
    "instead", "specifically", "moreover", "furthermore", "in other words",
)


def _fold(text: str) -> str:
    """Lowercase + normalize curly apostrophes for matching Yoast phrases."""
    t = (text or "").lower().replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("`", "'")
    return unicodedata.normalize("NFC", t)


def _phrases_for(lang: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    code = (lang or "en").lower()
    if code == "fr":
        return _FR_SINGLE, _FR_MULTI
    return _EN_SINGLE, _EN_MULTI


def sentence_has_transition(sentence: str, lang: str = "en") -> bool:
    """True if the sentence contains at least one Yoast-recognized connector."""
    plain = _fold(sentence)
    if not plain.strip():
        return False
    singles, multis = _phrases_for(lang)
    # Longest multi-word phrases first to avoid partial misses.
    for phrase in sorted(multis, key=len, reverse=True):
        if _fold(phrase) in plain:
            return True
    # Whole-word match for single-token connectors.
    tokens = set(re.findall(r"[\w'-]+", plain, flags=re.UNICODE))
    for word in singles:
        if _fold(word) in tokens:
            return True
    return False


def transition_ratio(sentences: list[str], lang: str = "en") -> float:
    if not sentences:
        return 0.0
    hit = sum(1 for s in sentences if sentence_has_transition(s, lang))
    return hit / len(sentences)


def meets_threshold(sentences: list[str], lang: str = "en") -> bool:
    if len(sentences) < 4:
        return True  # too short to score meaningfully
    return transition_ratio(sentences, lang) + 1e-9 >= MIN_TRANSITION_RATIO


def prompt_examples(lang: str = "en") -> str:
    code = (lang or "en").lower()
    words = FR_PROMPT_EXAMPLES if code == "fr" else EN_PROMPT_EXAMPLES
    return ", ".join(words)
