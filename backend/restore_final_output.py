"""One-off helper: rebuild final_output.md from fact_check corrected article."""

from __future__ import annotations

import re
import sys

from backend import artifacts
from backend import final_output_enforce


def extract_corrected_article(fact_check: str) -> str:
    start = fact_check.find("---CORRECTED ARTICLE START---")
    end = fact_check.find("---CORRECTED ARTICLE END---")
    if start == -1 or end == -1:
        return ""
    return fact_check[start + len("---CORRECTED ARTICLE START---") : end].strip()


def wrap_as_final_output(article_md: str, *, title: str = "") -> str:
    h1 = title or "Article"
    m = re.search(r"^#\s+(.+)$", article_md, re.M)
    if m:
        h1 = m.group(1).strip()
    return (
        "---PUBLISHING METADATA START---\n"
        f"H1 TITLE: {h1}\n"
        "META DESCRIPTION: [restored — re-run final output or edit]\n"
        "PRIMARY KEYWORD: \n"
        "SECONDARY KEYWORDS: \n"
        "ESTIMATED WORD COUNT: [pending]\n"
        "INTERNAL LINKS ADDED: 0\n"
        "STATUS: RESTORED FROM FACT CHECK\n"
        "---PUBLISHING METADATA END---\n\n"
        "---FINAL ARTICLE START---\n"
        f"{article_md.strip()}\n"
        "---FINAL ARTICLE END---\n"
    )


def restore(client_id: str, run_id: str) -> str:
    fc = artifacts.load_artifact(client_id, run_id, "fact_check")
    article = extract_corrected_article(fc)
    if not article:
        raise ValueError("No corrected article in fact_check")
    wrapped = wrap_as_final_output(article)
    return final_output_enforce.enforce_final_output(
        wrapped, client_id, run_id, allow_llm_repair=False
    )


if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else "arsuno"
    rid = sys.argv[2] if len(sys.argv) > 2 else "2026-05-26_00-21-06"
    out = restore(cid, rid)
    artifacts.save_artifact(cid, rid, "final_output", out)
    print(f"Restored {cid}/{rid} final_output ({len(out)} chars)")
