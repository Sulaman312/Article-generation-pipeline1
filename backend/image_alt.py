"""Image alt text: a meaningful sentence, never a slug, never a hyphen.

The draft writes images as ``![alt text](IMAGE: slug)``. Models often put the slug
(``ai-resume-screening-recruiter-review``) or a hyphenated phrase in the alt text.
This module cleans every alt text and reports the ones that are still too poor to use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Every kind of hyphen / dash, plus underscores used as word separators.
_DASH_CHARS = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2e3a\u2e3b_"
_DASH_RE = re.compile(f"[{re.escape(_DASH_CHARS)}]+")
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\n]*)\)")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_WORD_RE = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)?", re.UNICODE)

MIN_ALT_WORDS = 3
_GENERIC_ALTS = {
    "image", "photo", "picture", "illustration", "visuel", "photo illustration",
    "image illustration", "hero", "hero image", "alt", "alt text", "img",
    "texte alternatif", "capture", "screenshot",
}
_TAKEAWAY_HEADING = re.compile(
    r"^(key\s+takeaways?|à\s+retenir|points?\s+cl[ée]s?)\b", re.I
)


def strip_hyphens(text: str) -> str:
    """Replace every hyphen/dash by a space and tidy the spacing."""
    out = _DASH_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", out).strip()


def _slug_of(src: str) -> str:
    value = (src or "").strip()
    if value.upper().startswith("IMAGE:"):
        return value[6:].strip()
    return ""


def _looks_like_slug(alt: str) -> bool:
    """A single token joined with hyphens/underscores, e.g. ai-resume-screening."""
    a = (alt or "").strip()
    return bool(a) and " " not in a and bool(_DASH_RE.search(a))


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _derive(alt: str, slug: str, heading: str) -> str:
    """Best readable alt text from what we have, strongest source first."""
    for candidate in (strip_hyphens(alt), strip_hyphens(slug), strip_hyphens(heading)):
        if len(_WORD_RE.findall(candidate)) >= MIN_ALT_WORDS and not _is_generic(candidate):
            return _sentence_case(candidate)
    # Combine what is available so the result is at least descriptive.
    parts = [p for p in (strip_hyphens(alt), strip_hyphens(slug), strip_hyphens(heading)) if p]
    merged = " ".join(dict.fromkeys(" ".join(parts).split()))
    return _sentence_case(merged)


def _is_generic(alt: str) -> bool:
    return strip_hyphens(alt).lower() in _GENERIC_ALTS


def normalize_image_alts(text: str) -> str:
    """Clean the alt text of every markdown image in ``text``.

    - hyphens and dashes become spaces;
    - an alt text that is a slug, empty, or generic ("image") is rebuilt from the
      image slug (``IMAGE: slug``) or, failing that, from the nearest heading.
    Image targets (the slug itself, real URLs) are never changed.
    """
    if not text or "![" not in text:
        return text

    heading = ""
    out_lines: list[str] = []
    for line in text.split("\n"):
        hm = _HEADING_RE.match(line.strip())
        if hm and not _TAKEAWAY_HEADING.match(hm.group(2)):
            heading = hm.group(2)

        def _sub(m: re.Match[str]) -> str:
            alt = m.group("alt")
            slug = _slug_of(m.group("src"))
            poor = (
                not alt.strip()
                or _looks_like_slug(alt)
                or _is_generic(alt)
                or len(_WORD_RE.findall(strip_hyphens(alt))) < MIN_ALT_WORDS
            )
            new_alt = _derive(alt, slug, heading) if poor else strip_hyphens(alt)
            new_alt = new_alt.replace("[", "(").replace("]", ")")
            return f"![{new_alt}]({m.group('src')})"

        out_lines.append(_IMAGE_RE.sub(_sub, line))
    return "\n".join(out_lines)


@dataclass(frozen=True)
class AltProblem:
    alt: str
    reason: str


def find_alt_problems(text: str) -> list[AltProblem]:
    """Alt texts that still contain a hyphen, are generic, or are too short."""
    problems: list[AltProblem] = []
    for m in _IMAGE_RE.finditer(text or ""):
        alt = m.group("alt").strip()
        if _DASH_RE.search(alt):
            problems.append(AltProblem(alt, "contient un trait d'union / hyphen"))
        elif not alt or _is_generic(alt) or len(_WORD_RE.findall(alt)) < MIN_ALT_WORDS:
            problems.append(AltProblem(alt, "trop court ou trop générique"))
    return problems
