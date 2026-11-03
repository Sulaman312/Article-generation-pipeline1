"""Anthropic Claude API — editorial pipeline LLM steps.

Environment (see repo `.env.example`):
  ANTHROPIC_API_KEY  — Anthropic or OpenRouter API key
  ANTHROPIC_BASE_URL — optional; set ``https://openrouter.ai/api`` for OpenRouter
  CLAUDE_MODEL       — Anthropic id or OpenRouter slug (e.g. ``anthropic/claude-sonnet-4.6``)

Supports cooperative cancel via ``backend.job_control`` (streaming + chunk checks).
Supports Anthropic/OpenRouter prompt caching via ``CachedPrompt`` (cache_control + session_id).
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Sequence, TYPE_CHECKING

from .. import config
from .. import job_control

if TYPE_CHECKING:
    from ..prompt_cache import CachedPrompt

logger = logging.getLogger(__name__)

_client = None
LAST_CACHE_USAGE: dict[str, Any] | None = None

_BATCH_FINAL = frozenset({"completed", "failed", "expired", "cancelled", "canceled", "ended"})
_BATCH_FAILED = frozenset({"failed", "expired", "cancelled", "canceled"})


class BatchFailed(RuntimeError):
    """Batch API request ended without a usable result."""


def _safe_error_detail(exc: Exception) -> str:
    """Return useful provider diagnostics without leaking the API key."""
    detail = str(exc).strip() or type(exc).__name__
    if config.ANTHROPIC_API_KEY:
        detail = detail.replace(config.ANTHROPIC_API_KEY, "[REDACTED]")
    return detail[:1000]


def _get_client():
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to `.env` (see env.example)."
            )
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e
        kwargs = {"api_key": config.ANTHROPIC_API_KEY}
        if config.ANTHROPIC_BASE_URL:
            kwargs["base_url"] = config.ANTHROPIC_BASE_URL
            logger.info(
                "Claude client using custom base_url=%s model=%s",
                config.ANTHROPIC_BASE_URL,
                config.CLAUDE_MODEL,
            )
        else:
            # Always pass the direct API URL explicitly. If we pass nothing, the SDK
            # reads ANTHROPIC_BASE_URL from the environment itself, and a variable that
            # exists but is empty (common on Railway) becomes "" and every request fails
            # with "Request URL is missing an 'http://' or 'https://' protocol".
            kwargs["base_url"] = "https://api.anthropic.com"
        _client = anthropic.Anthropic(**kwargs)
    return _client


def _as_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _usage_attr(usage: Any, *names: str) -> int | None:
    for name in names:
        if isinstance(usage, dict):
            got = _as_int(usage.get(name))
        else:
            got = _as_int(getattr(usage, name, None))
        if got is not None:
            return got
    return None


def _usage_cache_fields(usage: Any) -> tuple[int | None, int | None, int | None]:
    """Extract (cache_read, cache_write, input_tokens) from provider usage."""
    if usage is None:
        return None, None, None

    cache_read = _usage_attr(
        usage,
        "cache_read_input_tokens",
        "cache_read_tokens",
        "cached_tokens",
    )
    cache_write = _usage_attr(
        usage,
        "cache_creation_input_tokens",
        "cache_write_tokens",
        "cache_creation_tokens",
    )
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
    else:
        details = getattr(usage, "prompt_tokens_details", None) or getattr(
            usage, "input_tokens_details", None
        )
    if details is not None:
        if cache_read is None:
            cache_read = _usage_attr(details, "cached_tokens", "cache_read_input_tokens")
        if cache_write is None:
            cache_write = _usage_attr(
                details, "cache_write_tokens", "cache_creation_input_tokens"
            )

    input_tokens = _usage_attr(usage, "input_tokens", "prompt_tokens")
    return cache_read, cache_write, input_tokens


def _client_run_from_session(session_id: str | None) -> tuple[str, str] | None:
    if not session_id or not session_id.startswith("article:"):
        return None
    rest = session_id[len("article:") :]
    if ":" not in rest:
        return None
    client_id, run_id = rest.rsplit(":", 1)
    if not client_id or not run_id:
        return None
    return client_id, run_id


def _persist_cache_usage(record: dict[str, Any], session_id: str | None) -> None:
    parsed = _client_run_from_session(session_id)
    if parsed is None:
        return
    client_id, run_id = parsed
    path = config.CLIENTS_DIR / client_id / "runs" / run_id / "cache_usage.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("could not persist cache usage to %s", path, exc_info=True)


def _log_cache_usage(step_label: str, usage: Any, *, session_id: str | None = None) -> None:
    global LAST_CACHE_USAGE
    cache_read, cache_write, input_tokens = _usage_cache_fields(usage)
    if cache_read is None and cache_write is None and input_tokens is None:
        LAST_CACHE_USAGE = {
            "step": step_label,
            "session_id": session_id or "",
            "available": False,
        }
        logger.info(
            "%s: Claude usage unavailable (no cache metrics on response). "
            "A cache hit shows as prompt_cache read>0 on the next call in this session.",
            step_label,
        )
        _persist_cache_usage(LAST_CACHE_USAGE, session_id)
        return
    hit_rate = None
    if input_tokens and cache_read is not None and input_tokens > 0:
        hit_rate = round(100.0 * cache_read / input_tokens, 1)
    working = bool(cache_read and cache_read > 0)
    warming = bool(cache_write and cache_write > 0 and not working)
    LAST_CACHE_USAGE = {
        "step": step_label,
        "session_id": session_id or "",
        "available": True,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "input_tokens": input_tokens,
        "hit_rate": hit_rate,
        "hit": working,
        "warming": warming,
    }
    logger.info(
        "%s: prompt_cache read=%s write=%s input=%s hit_rate=%s%% %s session=%s",
        step_label,
        cache_read if cache_read is not None else "?",
        cache_write if cache_write is not None else "?",
        input_tokens if input_tokens is not None else "?",
        hit_rate if hit_rate is not None else "?",
        "HIT" if working else ("WARM" if warming else "MISS"),
        session_id or "-",
    )
    _persist_cache_usage(LAST_CACHE_USAGE, session_id)


def _is_openrouter() -> bool:
    base = (config.ANTHROPIC_BASE_URL or "").lower()
    return "openrouter.ai" in base


def _count_cache_breakpoints(prompt: CachedPrompt) -> int:
    n = 0
    for block in prompt.system_blocks():
        if isinstance(block, dict) and block.get("cache_control"):
            n += 1
    for msg in prompt.messages():
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("cache_control"):
                n += 1
    return n


def _stream_kwargs_for_cached(
    prompt: CachedPrompt,
    *,
    model: str,
    max_tok: int,
    temp: float,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tok,
        "temperature": temp,
        "system": prompt.system_blocks(),
        "messages": prompt.messages(),
    }
    extra_body: dict[str, Any] = {}
    if _is_openrouter():
        # OpenRouter omits usage (and therefore cache hits) on streams unless asked.
        extra_body["stream_options"] = {"include_usage": True}
        extra_body["usage"] = {"include": True}
        if prompt.session_id:
            # Sticky provider routing so cache hits are not lost to provider flips.
            extra_body["session_id"] = prompt.session_id
    if extra_body:
        kwargs["extra_body"] = extra_body
    logger.debug(
        "%s: cache_control breakpoints=%s openrouter=%s session=%s",
        prompt.step_label,
        _count_cache_breakpoints(prompt),
        _is_openrouter(),
        prompt.session_id or "-",
    )
    return kwargs


def _stream_complete(
    *,
    stream_kwargs: dict[str, Any],
    step_label: str,
    session_id: str | None = None,
) -> str:
    client = _get_client()
    parts: list[str] = []
    final_message = None
    with client.messages.stream(**stream_kwargs) as stream:
        for text in stream.text_stream:
            if job_control.is_cancelled():
                try:
                    stream.close()
                except Exception:
                    logger.debug(
                        "%s: stream close after cancel raised",
                        step_label,
                        exc_info=True,
                    )
                raise job_control.JobCancelled("Pipeline step cancelled by user")
            parts.append(text)
        try:
            final_message = stream.get_final_message()
        except Exception:
            logger.debug("%s: get_final_message failed", step_label, exc_info=True)
    raw = "".join(parts).strip()
    if not raw:
        raise ValueError("Claude returned empty content")
    if final_message is not None:
        _log_cache_usage(
            step_label,
            getattr(final_message, "usage", None),
            session_id=session_id,
        )
    job_control.raise_if_cancelled()
    return raw


def chat_complete(
    system_msg: str | CachedPrompt,
    user_msg: str | None = None,
    *,
    step_label: str = "pipeline step",
    max_tokens: int | None = None,
    temperature: float | None = None,
    session_id: str | None = None,
) -> str:
    """Call Claude with system + user messages; retry once after 3s on failure.

    Uses streaming so cooperative cancel can close the HTTP body promptly.

    Pass a ``CachedPrompt`` as ``system_msg`` (and omit ``user_msg``) to enable
    Anthropic/OpenRouter prompt caching with a stable prefix + breakpoint.
    """
    from .. import prompt_cache as pc

    model = config.CLAUDE_MODEL
    max_tok = max_tokens if max_tokens is not None else config.MAX_TOKENS
    temp = temperature if temperature is not None else config.TEMPERATURE

    cached: CachedPrompt | None
    if isinstance(system_msg, pc.CachedPrompt):
        cached = system_msg
        step_label = cached.step_label or step_label
        session_id = cached.session_id or session_id
    else:
        cached = None
        if user_msg is None:
            raise TypeError("user_msg is required when system_msg is a string")

    last_exc: Exception | None = None
    max_attempts = max(1, int(getattr(config, "CLAUDE_MAX_ATTEMPTS", 2)))
    for attempt in range(max_attempts):
        job_control.raise_if_cancelled()
        try:
            if cached is not None:
                stream_kwargs = _stream_kwargs_for_cached(
                    cached, model=model, max_tok=max_tok, temp=temp
                )
            else:
                stream_kwargs = {
                    "model": model,
                    "max_tokens": max_tok,
                    "temperature": temp,
                    "system": system_msg,
                    "messages": [{"role": "user", "content": user_msg}],
                }
                if session_id and _is_openrouter():
                    stream_kwargs["extra_body"] = {"session_id": session_id}
            raw = _stream_complete(
                stream_kwargs=stream_kwargs,
                step_label=step_label,
                session_id=session_id,
            )
            if cached is not None and cached.enable_cache:
                pc.mark_session_warmed(cached.session_id)
            return raw
        except job_control.JobCancelled:
            raise
        except Exception as e:
            last_exc = e
            detail = _safe_error_detail(e)
            logger.warning(
                "%s: Claude API attempt %s failed (%s): %s",
                step_label,
                attempt + 1,
                type(e).__name__,
                detail,
            )
            if attempt < max_attempts - 1:
                if job_control.is_cancelled():
                    raise job_control.JobCancelled(
                        "Pipeline step cancelled by user"
                    )
                time.sleep(3 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"Claude API call failed after {max_attempts} attempt(s) for {step_label}: "
                    f"{type(e).__name__}: {detail}"
                ) from last_exc
    raise AssertionError("unreachable")


def warm_cache_then_map(
    prompts: Sequence[CachedPrompt],
    *,
    call: Callable[..., str] | None = None,
    max_workers: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> list[str]:
    """Warm the shared prefix with the first call, then run the rest (optionally parallel).

    Pipeline steps are usually sequential (natural warming). Use this when firing
    multiple near-identical cached calls in one burst.
    """
    if not prompts:
        return []
    runner = call or (
        lambda p: chat_complete(
            p,
            step_label=p.step_label,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    )
    results: list[str | None] = [None] * len(prompts)
    results[0] = runner(prompts[0])
    rest = list(enumerate(prompts[1:], start=1))
    if not rest:
        return [results[0] or ""]

    workers = max_workers if max_workers is not None else min(4, len(rest))
    if workers <= 1:
        for idx, prompt in rest:
            results[idx] = runner(prompt)
        return [r or "" for r in results]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(runner, prompt): idx for idx, prompt in rest}
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
    return [r or "" for r in results]


def _openrouter_api_v1() -> str:
    base = (config.ANTHROPIC_BASE_URL or "https://openrouter.ai/api").rstrip("/")
    if base.endswith("/v1"):
        return base
    return base + "/v1"


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    import httpx

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    headers = {
        "Authorization": f"Bearer {config.ANTHROPIC_API_KEY}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    last_exc: Exception | None = None
    for attempt in range(3):
        job_control.raise_if_cancelled()
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.request(method, url, headers=headers, json=payload)
            if response.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Unexpected JSON from {url}")
            return data
        except job_control.JobCancelled:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"{method} {url} failed: {_safe_error_detail(exc)}"
            ) from last_exc
    raise RuntimeError(f"{method} {url} failed: {_safe_error_detail(last_exc or RuntimeError('retry'))}")


def message_body_for_cached(
    prompt: CachedPrompt,
    *,
    max_tokens: int,
    temperature: float,
    include_model: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": prompt.system_blocks(),
        "messages": prompt.messages(),
    }
    if include_model:
        body["model"] = config.CLAUDE_MODEL
    if prompt.session_id and _is_openrouter():
        body["session_id"] = prompt.session_id
    return body


def _text_from_message_body(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    content = body.get("content")
    if isinstance(content, list):
        parts = [
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") in ("text", "output_text")
        ]
        joined = "".join(parts).strip()
        if joined:
            return joined
        if all(isinstance(block, str) for block in content):
            return "".join(content).strip()
    if isinstance(content, str) and content.strip():
        return content.strip()
    output = body.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            inner = item.get("content")
            if isinstance(inner, list):
                for block in inner:
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(str(block["text"]))
            elif item.get("text"):
                parts.append(str(item["text"]))
        joined = "".join(parts).strip()
        if joined:
            return joined
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            msg_content = message.get("content")
            if isinstance(msg_content, str):
                return msg_content.strip()
    return ""


def extract_batch_text(batch: dict[str, Any], custom_id: str) -> str:
    """Pull assistant text for ``custom_id`` from an OpenRouter/Anthropic batch payload."""
    results = batch.get("results") or []
    match: dict[str, Any] | None = None
    for item in results:
        if isinstance(item, dict) and item.get("custom_id") == custom_id:
            match = item
            break
    if match is None and len(results) == 1 and isinstance(results[0], dict):
        match = results[0]
    if match is None:
        raise BatchFailed(
            f"Batch {batch.get('id') or '?'} has no result for {custom_id!r}"
        )
    error = match.get("error")
    if error:
        raise BatchFailed(f"Batch request {custom_id} failed: {error}")
    response = match.get("response") or {}
    body = response.get("body") if isinstance(response, dict) else None
    text = _text_from_message_body(body)
    if not text:
        raise BatchFailed(f"Batch request {custom_id} returned empty text")
    usage = None
    if isinstance(body, dict):
        usage = body.get("usage")
    if usage:
        _log_cache_usage(f"batch:{custom_id}", usage, session_id=None)
    return text


def submit_cached_batch(
    prompt: CachedPrompt,
    *,
    max_tokens: int,
    temperature: float,
    custom_id: str,
) -> dict[str, str]:
    """Submit one cached Messages request to the Batch API (~50% of sync price)."""
    if _is_openrouter():
        payload = {
            "endpoint": "/v1/messages",
            "model": config.CLAUDE_MODEL,
            "completion_window": "24h",
            "requests": [
                {
                    "custom_id": custom_id,
                    "body": message_body_for_cached(
                        prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        include_model=False,
                    ),
                }
            ],
        }
        data = _http_json("POST", f"{_openrouter_api_v1()}/batches", payload=payload)
        batch_id = str(data.get("id") or "").strip()
        if not batch_id:
            raise RuntimeError(f"Batch submit returned no id: {data!r}"[:500])
        logger.info(
            "%s: submitted OpenRouter batch id=%s custom_id=%s",
            prompt.step_label,
            batch_id,
            custom_id,
        )
        return {"id": batch_id, "provider": "openrouter"}

    client = _get_client()
    batch = client.messages.batches.create(
        requests=[
            {
                "custom_id": custom_id,
                "params": message_body_for_cached(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    include_model=True,
                ),
            }
        ]
    )
    batch_id = str(getattr(batch, "id", "") or "").strip()
    if not batch_id:
        raise RuntimeError("Anthropic batch submit returned no id")
    logger.info(
        "%s: submitted Anthropic batch id=%s custom_id=%s",
        prompt.step_label,
        batch_id,
        custom_id,
    )
    return {"id": batch_id, "provider": "anthropic"}


def get_batch(batch_id: str) -> dict[str, Any]:
    if _is_openrouter():
        return _http_json("GET", f"{_openrouter_api_v1()}/batches/{batch_id}")
    client = _get_client()
    batch = client.messages.batches.retrieve(batch_id)
    if hasattr(batch, "model_dump"):
        data = batch.model_dump()
        if isinstance(data, dict):
            return data
    return {"id": batch_id, "status": getattr(batch, "processing_status", None)}


def _anthropic_batch_text(batch_id: str, custom_id: str) -> str:
    client = _get_client()
    for item in client.messages.batches.results(batch_id):
        if getattr(item, "custom_id", None) != custom_id:
            continue
        result = getattr(item, "result", None)
        result_type = getattr(result, "type", None) if result is not None else None
        if result_type != "succeeded":
            raise BatchFailed(
                f"Anthropic batch {custom_id} result type={result_type}"
            )
        message = getattr(result, "message", None)
        usage = getattr(message, "usage", None) if message is not None else None
        if usage is not None:
            _log_cache_usage(f"batch:{custom_id}", usage)
        content = getattr(message, "content", None) if message is not None else None
        parts: list[str] = []
        if isinstance(content, list):
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        joined = "".join(parts).strip()
        if joined:
            return joined
        raise BatchFailed(f"Anthropic batch {custom_id} returned empty text")
    raise BatchFailed(f"Anthropic batch {batch_id} has no result for {custom_id}")


def wait_for_batch(
    batch_id: str,
    *,
    custom_id: str,
    poll_seconds: float = 20.0,
    timeout: float = 20 * 3600,
) -> str:
    """Poll until the batch finishes and return the assistant text for ``custom_id``."""
    deadline = time.monotonic() + max(30.0, timeout)
    delay = max(5.0, poll_seconds)
    while True:
        job_control.raise_if_cancelled()
        if _is_openrouter():
            batch = get_batch(batch_id)
            status = str(batch.get("status") or "").lower()
            results_ready = status != "completed" or batch.get("results") is not None
            if status in _BATCH_FAILED:
                raise BatchFailed(
                    f"Batch {batch_id} ended as {status}: {batch.get('error') or ''}"
                )
            if status in _BATCH_FINAL and results_ready:
                return extract_batch_text(batch, custom_id)
        else:
            batch = get_batch(batch_id)
            status = str(
                batch.get("processing_status") or batch.get("status") or ""
            ).lower()
            if status in _BATCH_FAILED:
                raise BatchFailed(f"Batch {batch_id} ended as {status}")
            if status in _BATCH_FINAL or status == "ended":
                return _anthropic_batch_text(batch_id, custom_id)
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Batch {batch_id} still running after {int(timeout)}s"
            )
        time.sleep(delay)
        delay = min(60.0, delay * 1.3)
