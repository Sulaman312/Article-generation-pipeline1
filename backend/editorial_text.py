"""Sentence boundaries that preserve initials, honorifics and exact source offsets."""
import re

_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_ABBREVIATION = re.compile(
    r"\b(?:Dr|Pr|Prof|Mme|Mmes|Mr|Mrs|Ms)\.(?=\s+\w)|"
    r"\b[A-ZÀ-ÖØ-Þ]\.(?=\s*[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ])|"
    r"\b(?:e\.g|i\.e)\.", re.UNICODE,
)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    # Replacement keeps the original length, so offsets still address the draft.
    masked = _ABBREVIATION.sub(lambda m: m.group().replace('.', '\u2024'), text)
    spans = []
    start = 0
    for boundary in _BOUNDARY.finditer(masked):
        end = boundary.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = boundary.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def split_sentences(text: str) -> list[str]:
    return [text[a:b] for a, b in sentence_spans(text)]
