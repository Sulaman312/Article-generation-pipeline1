"""Cheap editorial signals for the fact checker, without inventing corrections."""
from __future__ import annotations
import re
from . import french_language
from .editorial_text import sentence_spans
from .fact_check_contract import paragraphs, numbers

_INITIAL_END = re.compile(r"\b(?:par|by)\s+(?:[A-ZÀ-ÖØ-Þ][\w’'-]+\s+){1,3}[A-Z]\.$")
_NO_SUBJECT = re.compile(r"^(?:Publié|Publiée|Published)\b[^\n]+,\s*(?:a|ont|has|have)\s+", re.I)


def check_draft(draft: str, source_texts: dict[str, str] | None = None) -> list[dict]:
    findings = []
    for issue in french_language.scan_french(draft, spelling=False, english=False, banned=False):
        findings.append({'code': issue.code, 'message': issue.message(), 'severity': 'error'})
    for p in paragraphs(draft):
        for index, (a, b) in enumerate(sentence_spans(p.text), 1):
            sentence = p.text[a:b]
            base = {'section': p.section, 'paragraph': p.number, 'sentence': index, 'severity': 'warning'}
            if _INITIAL_END.search(sentence):
                findings.append({**base, 'code': 'dangling_initial', 'message': 'Sentence ends with an initial; verify that the surname was not truncated.'})
            if _NO_SUBJECT.search(sentence):
                findings.append({**base, 'code': 'possible_missing_subject', 'message': 'Possible missing subject after the publication clause. Verify grammar.'})
            for url, source in (source_texts or {}).items():
                # A missing number is a signal, not proof of an incorrect statistic.
                if url.rstrip('/') not in sentence:
                    continue
                prose = re.sub(r'https?://[^\s)]+', '', sentence)
                group = re.search(r"(?:deux|2|trois|3)\s+groupes?\s+de\s+(\d+)", prose, re.I)
                total = re.search(r"(?:a\s+total\s+of|total\s+(?:de|of))\s+(\d+)\s+(?:participants|subjects|patients|personnes)", source, re.I)
                if group and total and group[1] == total[1]:
                    findings.append({**base, 'code': 'group_total_scope', 'source_url': url,
                                     'message': 'Possible confusion between total participants and participants per group. Verify the study; do not infer group sizes.'})
                unknown = numbers(prose) - numbers(source)
                if unknown:
                    findings.append({**base, 'code': 'numeric_source_mismatch', 'source_url': url,
                                     'message': 'Numbers not found literally in the supplied source: ' + ', '.join(sorted(unknown)) + '. Check the meaning and participant/group counts; do not infer a replacement.'})
    return findings
