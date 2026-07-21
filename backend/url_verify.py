"""HTTP URL reachability checks for Perplexity-sourced citations."""

from __future__ import annotations

import re
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_URL_RE = re.compile(r"https?://[^\s\)\]\>\"']+", re.IGNORECASE)
_TRAIL_PUNCT = ".,;:!?)\"'"


@dataclass(frozen=True)
class UrlCheckResult:
    url: str
    ok: bool
    status: int | None
    detail: str


def extract_http_urls(text: str, *, limit: int = 40) -> list[str]:
    """Return unique http(s) URLs found in text, in order of first appearance."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        raw = m.group(0).rstrip(_TRAIL_PUNCT)
        if raw.endswith("]"):
            raw = raw[:-1]
        if not raw or raw in seen:
            continue
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        seen.add(raw)
        out.append(raw)
        if len(out) >= limit:
            break
    return out


def check_url(url: str, *, timeout: float = 8.0) -> UrlCheckResult:
    """HEAD then GET fallback — ok when status is 2xx/3xx."""
    target = (url or "").strip()
    if not target:
        return UrlCheckResult(url="", ok=False, status=None, detail="empty URL")

    ctx = ssl.create_default_context()
    headers = {
        "User-Agent": "ContentFlowURLCheck/1.0 (+article-generation-pipeline)",
        "Accept": "*/*",
    }

    for method in ("HEAD", "GET"):
        try:
            req = Request(target, headers=headers, method=method)
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                if 200 <= int(status) < 400:
                    return UrlCheckResult(
                        url=target, ok=True, status=int(status), detail=f"{method} ok"
                    )
                if method == "HEAD" and int(status) in (403, 405, 501):
                    continue
                return UrlCheckResult(
                    url=target,
                    ok=False,
                    status=int(status),
                    detail=f"{method} HTTP {status}",
                )
        except HTTPError as e:
            code = int(e.code)
            if method == "HEAD" and code in (403, 405, 501):
                continue
            if 200 <= code < 400:
                return UrlCheckResult(
                    url=target, ok=True, status=code, detail=f"{method} HTTPError {code}"
                )
            return UrlCheckResult(
                url=target, ok=False, status=code, detail=f"{method} HTTPError {code}"
            )
        except URLError as e:
            return UrlCheckResult(
                url=target, ok=False, status=None, detail=f"network: {e.reason}"
            )
        except Exception as e:  # noqa: BLE001 — surface any transport failure
            return UrlCheckResult(
                url=target, ok=False, status=None, detail=f"error: {type(e).__name__}"
            )

    return UrlCheckResult(url=target, ok=False, status=None, detail="unreachable")


def check_urls(
    urls: Iterable[str], *, max_workers: int = 6, timeout: float = 8.0
) -> list[UrlCheckResult]:
    items = [u for u in urls if (u or "").strip()]
    if not items:
        return []
    results: dict[str, UrlCheckResult] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        futures = {
            pool.submit(check_url, u, timeout=timeout): u for u in items
        }
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return [results[u] for u in items]


def format_url_verification_section(
    results: list[UrlCheckResult], *, title: str = "URL verification (pipeline)"
) -> str:
    """Markdown section the research_audit step must respect."""
    lines = [f"## {title}"]
    if not results:
        lines.append("- No http(s) URLs found to verify.")
        return "\n".join(lines) + "\n"
    ok_n = sum(1 for r in results if r.ok)
    lines.append(f"- Checked {len(results)} URL(s); {ok_n} reachable (2xx/3xx).")
    for r in results:
        flag = "OK" if r.ok else "FAIL"
        status = r.status if r.status is not None else "-"
        lines.append(f"- [{flag}] `{r.url}` — HTTP {status} — {r.detail}")
    return "\n".join(lines) + "\n"


def append_url_verification(text: str, *, limit: int = 25) -> str:
    """Extract URLs from text, check them, append verification section."""
    body = (text or "").rstrip()
    urls = extract_http_urls(body, limit=limit)
    results = check_urls(urls)
    section = format_url_verification_section(results)
    cleaned = re.sub(
        r"\n##\s+URL verification \(pipeline\).*?(?=\n##\s|\Z)",
        "\n",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ).rstrip()
    return cleaned + "\n\n" + section
