"""Structured fact-checking: exact locations, bounded repair and deterministic reports.

Only replacement text and the resulting article enter publication language checks.
Internal explanations and quoted claims are evidence, never publishable copy.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import unicodedata
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from . import config, french_language, job_control, quality_execution
from .editorial_text import sentence_spans

logger = logging.getLogger(__name__)

ISSUE_TYPES = ["fabricated statistic", "outdated claim", "overgeneralization",
               "unverifiable claim", "incorrect definition", "misleading framing",
               "company claim error", "broken sentence"]
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["assessment", "company_review", "issues"],
    "properties": {
        "assessment": {"enum": ["CLEAN", "MINOR ISSUES", "SIGNIFICANT ISSUES"]},
        "company_review": {"type": "string", "maxLength": 4000},
        "issues": {"type": "array", "maxItems": 40, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["section", "paragraph", "sentence", "anchor", "claim",
                         "issue_type", "action", "fix", "explanation", "source_url", "evidence_quote"],
            "properties": {
                "section": {"type": "string", "maxLength": 300},
                "paragraph": {"type": "integer", "minimum": 1},
                "sentence": {"type": "integer", "minimum": 1},
                "anchor": {"type": "string", "minLength": 1, "maxLength": 300},
                "claim": {"type": "string", "minLength": 1, "maxLength": 1000},
                "issue_type": {"enum": ISSUE_TYPES},
                "action": {"enum": ["corrected", "removed", "flagged"]},
                "fix": {"type": "string", "maxLength": 2000},
                "explanation": {"type": "string", "minLength": 1, "maxLength": 2000},
                "source_url": {"type": "string", "maxLength": 2000},
                "evidence_quote": {"type": "string", "maxLength": 4000},
            },
        }},
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA)
_OMISSION = re.compile(r"\[\s*(?:…|\.{3})\s*\]")
_ELLIPSIS = re.compile(r"…|\.{3}")
_NUMBER = re.compile(r"(?<!\w)\d+(?:[ ,\u00a0\u202f.]\d+)*(?:%|\b)")
MAX_FLAG_CLAIM_WORDS = 12
MAX_EDIT_CLAIM_WORDS = 40


def _leading_words(sentence: str, count: int) -> str:
    match = re.match(r"(?:\S+\s+){0,%d}\S+" % (count - 1), sentence)
    return match.group() if match else sentence


def _norm(text: str) -> str:
    """Whitespace/quote/dash-insensitive form used only to *match* evidence quotes."""
    value = unicodedata.normalize('NFKC', text or '')
    value = value.translate(str.maketrans({'\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-',
                                           '*': '', '_': ''}))
    return re.sub(r"\s+", ' ', value).strip().casefold()


def _find_source(evidence: str, url: str, sources: dict[str, str]) -> str | None:
    """Return the url of a supplied source containing the quote (named source first)."""
    needle = _norm(evidence)
    if not needle:
        return None
    candidates = ([url] if url in sources else []) + [u for u in sources if u != url]
    for candidate in candidates:
        if needle in _norm(sources[candidate]):
            return candidate
    return None


def _note(lang: str, fr: str, en: str) -> str:
    return fr if lang == 'fr' else en


@dataclass(frozen=True)
class Paragraph:
    section: str
    number: int
    start: int
    text: str


def paragraphs(draft: str) -> list[Paragraph]:
    result = []
    section = ""
    block = []
    start = 0
    offset = 0

    def flush():
        if block:
            body = ''.join(block).rstrip()
            if body and not re.fullmatch(r"!\[[^]]*\]\([^)]*\)", body):
                result.append(Paragraph(section, len(result) + 1, start, body))
            block.clear()

    for line in draft.splitlines(keepends=True):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading or not line.strip() or line.strip().startswith('---'):
            flush()
            if heading:
                section = heading[1]
        else:
            if not block:
                start = offset
            block.append(line)
        offset += len(line)
    flush()
    return result


def annotated_draft(draft: str) -> str:
    lines = []
    for p in paragraphs(draft):
        lines.append(f"SECTION: {p.section}\nPARAGRAPH: {p.number}")
        for index, (a, b) in enumerate(sentence_spans(p.text), 1):
            lines.append(f"SENTENCE {index}: {p.text[a:b]}")
    return '\n'.join(lines)


def numbers(text: str) -> set[str]:
    result = set()
    for match in _NUMBER.finditer(text):
        value = re.sub(r"[ \u00a0\u202f]", '', match.group()).rstrip('%')
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", value):
            value = value.replace(',', '')
        else:
            value = value.replace(',', '.')
        result.add(value)
    return result



class FactCheckError(RuntimeError):
    def __init__(self, errors: list[str], text: str):
        self.errors = errors
        self.text = text
        super().__init__("Fact-check validation failed:\n" + '\n'.join(f"- {e}" for e in errors))


def parse_report(raw: str) -> dict:
    value = raw.strip()
    if value.startswith('```'):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", '', value, flags=re.I)
    try:
        report = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise FactCheckError([f"Return one complete JSON object: {exc}"], raw) from exc
    errors = [f"{'.'.join(map(str, e.absolute_path)) or 'report'}: {e.message}"
              for e in _VALIDATOR.iter_errors(report)]
    if errors:
        raise FactCheckError(errors, raw)
    return report


def validate_report(report: dict, draft: str, *, lang: str, glossary=None,
                    source_texts: dict[str, str] | None = None) -> tuple[dict, list[tuple[int, int, str]]]:
    data = copy.deepcopy(report)
    ps = paragraphs(draft)
    errors = []
    edits = []
    sources = source_texts or {}
    if (data['assessment'] == 'CLEAN') != (not data['issues']):
        errors.append('assessment must be CLEAN exactly when issues is empty')
    for index, issue in enumerate(data['issues'], 1):
        prefix = f"issues[{index - 1}]"
        if issue['paragraph'] > len(ps):
            errors.append(f"{prefix}.paragraph: number does not exist in the draft")
            continue
        p = ps[issue['paragraph'] - 1]
        spans = sentence_spans(p.text)
        if issue['section'] != p.section or issue['sentence'] > len(spans):
            errors.append(f"{prefix}: section or sentence does not match the indexed draft")
            continue
        a, b = spans[issue['sentence'] - 1]
        sentence = p.text[a:b]
        # The anchor is pure bookkeeping: derive it from the indexed sentence instead of
        # asking the model to copy it (a miscopy used to discard the whole report).
        issue['anchor'] = _leading_words(sentence, 6)
        claim = issue['claim']
        if issue['action'] == 'flagged':
            # A flagged claim never drives an edit, so repair it in code rather than fail.
            if (_ELLIPSIS.search(claim) or len(claim.split()) > MAX_FLAG_CLAIM_WORDS
                    or not re.search(r"\w", claim) or sentence.count(claim) != 1):
                claim = _leading_words(sentence, MAX_FLAG_CLAIM_WORDS)
                issue['claim'] = claim
        else:
            # corrected/removed claims define the edited span: they must stay exact.
            if _ELLIPSIS.search(claim) or len(claim.split()) > MAX_EDIT_CLAIM_WORDS:
                errors.append(f"{prefix}.claim: use at most {MAX_EDIT_CLAIM_WORDS} contiguous verbatim words, without ellipses")
            if not re.search(r"\w", claim):
                errors.append(f"{prefix}.claim: quote words, not punctuation alone")
            if sentence.count(claim) != 1:
                errors.append(f"{prefix}.claim: must occur exactly once, word for word, in the indexed sentence")
                continue
            claim_start = sentence.index(claim)
            claim_end = claim_start + len(claim)
            if ((claim_start and sentence[claim_start - 1].isalnum() and claim[0].isalnum())
                    or (claim_end < len(sentence) and sentence[claim_end].isalnum() and claim[-1].isalnum())):
                errors.append(f"{prefix}.claim: do not quote a partial word")
        if issue['action'] != 'corrected' and issue['fix']:
            errors.append(f"{prefix}.fix: must be empty for removed or flagged items")
        if issue['action'] == 'corrected' and not issue['fix'].strip():
            errors.append(f"{prefix}.fix: replacement text is required")
        # Never modify evidence/claim strings to make them pass a language test.
        fix = issue['fix']
        french_enabled = lang == 'fr' and config.FRENCH_QA_ENABLED
        if french_enabled and fix:
            fix = french_language.apply_glossary_replacements(fix, glossary)
            issue['fix'] = fix
        if re.search(r"(?m)^#{1,6}\s|---[A-Z]|(?:\r?\n){2}", fix):
            errors.append(f"{prefix}.fix: provide a fragment replacement, not a section or article")
        found = french_language.scan_french(
            fix, glossary=glossary, spelling=False, english=french_enabled, banned=french_enabled)
        errors.extend(f"{prefix}.fix: {i.message()}" for i in french_language.blocking_issues(found))
        # Evidence is checked leniently (quotes, dashes, spacing, case, wrong url) and never
        # discards the report: an unverifiable quote is dropped and the issue is left for a human.
        evidence = issue['evidence_quote']
        if evidence:
            found_url = _find_source(evidence, issue['source_url'], sources)
            if found_url is None:
                issue['evidence_quote'] = evidence = ''
                issue['explanation'] += _note(lang, " [Citation de la source non retrouvée dans le texte fourni : à vérifier.]",
                                              " [Source quote not found in the supplied text: please verify.]")
            else:
                issue['source_url'] = found_url
        replacement_numbers = numbers(fix)
        if replacement_numbers and issue['action'] == 'corrected' and (
                not evidence or not replacement_numbers <= numbers(evidence)):
            # A new number needs a verifiable source; otherwise do not touch the article.
            issue['action'], issue['fix'], fix = 'flagged', '', ''
            issue['explanation'] += _note(lang, " [Remplacement chiffré non appliqué faute de source vérifiable : revue humaine requise.]",
                                          " [Numeric replacement not applied: no verifiable source, human review required.]")
        if issue['action'] in {'corrected', 'removed'}:
            start = p.start + a + sentence.index(claim)
            edits.append((start, start + len(claim), fix if issue['action'] == 'corrected' else ''))
    edits.sort()
    if any(right[0] < left[1] for left, right in zip(edits, edits[1:])):
        errors.append('Corrections overlap; use one atomic replacement for each span')
    if errors:
        raise FactCheckError(errors, json.dumps(report, ensure_ascii=False))
    return data, edits


def apply_edits(draft: str, edits: list[tuple[int, int, str]]) -> str:
    result = draft
    for start, end, replacement in reversed(edits):
        result = result[:start] + replacement + result[end:]
    return result


def render_report(report: dict) -> tuple[str, list[dict]]:
    # Cleanup is restricted to human-facing commentary, never claim/anchor/fix.
    clean = lambda value: _OMISSION.sub(';', value)
    lines = ['---FACT CHECK START---', '---FACT CHECK REPORT START---',
             f"OVERALL ASSESSMENT: {report['assessment']}", f"TOTAL ISSUES FOUND: {len(report['issues'])}",
             f"COMPANY CLAIM REVIEW: {clean(report['company_review'])}", '', 'ISSUES FOUND:']
    corrections = []
    for n, issue in enumerate(report['issues'], 1):
        lines.extend([f"ISSUE #: {n}", f"LOCATION: {issue['section']} | P{issue['paragraph']} | S{issue['sentence']} | {issue['anchor']}",
                      f"ISSUE TYPE: {issue['issue_type']}", f"ACTION TAKEN: {issue['action']}",
                      f"CORRECTION OR FLAG: {clean(issue['explanation'])}", ''])
        if issue['source_url']:
            lines.append(f"SOURCE URL: {issue['source_url']}")
        if issue['evidence_quote']:
            lines.append(f"EVIDENCE: {issue['evidence_quote']}")
        corrections.append({'claim': issue['claim'], 'issue': issue['issue_type'],
                            'fix': issue['fix'], 'action': issue['action']})
    lines.append('ITEMS FLAGGED FOR HUMAN REVIEW:')
    for issue in report['issues']:
        if issue['action'] == 'flagged':
            lines.append(f"- P{issue['paragraph']}: {clean(issue['explanation'])}")
    lines.extend(['---FACT CHECK REPORT END---', '---FACT CHECK END---'])
    return '\n'.join(lines), corrections


def run_fact_check(generate, draft: str, *, lang: str, glossary=None,
                   source_texts: dict[str, str] | None = None, retries: int = 2):
    """Generate once and repair the same output at most twice; never rerun research."""
    feedback = ''
    raw = ''
    for attempt in range(min(2, max(0, retries)) + 1):
        job_control.raise_if_cancelled()
        raw = generate(feedback)
        quality_execution.candidate_output.set(raw)
        try:
            report = parse_report(raw)
            validated, edits = validate_report(report, draft, lang=lang, glossary=glossary, source_texts=source_texts)
            patched = apply_edits(draft, edits)
            # Check article copy, not the diagnostic report. Repairs are returned as
            # structured corrections so source quotes and offsets remain exact.
            found = french_language.scan_french(patched, glossary=glossary, spelling=False,
                                                english=(lang == 'fr' and config.FRENCH_QA_ENABLED),
                                                banned=(lang == 'fr' and config.FRENCH_QA_ENABLED))
            errors = french_language.blocking_issues(found)
            if errors:
                raise FactCheckError([f"Article: {i.message()}" for i in errors], raw)
            return validated, patched
        except FactCheckError as exc:
            logger.warning("fact_check validation attempt %s: %s", attempt + 1, exc)
            if attempt == min(2, max(0, retries)):
                raise FactCheckError(exc.errors, raw) from exc
            feedback = ('Correct only this fact-check JSON. Do not rerun research or rewrite the article. '
                        'Keep verbatim claims and correct every listed error. Return JSON only.\n'
                        + str(exc) + '\nPREVIOUS JSON:\n' + raw)
    raise AssertionError('unreachable')
