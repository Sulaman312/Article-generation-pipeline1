"""Anthropic Claude API — editorial pipeline LLM steps.

Environment (see repo `.env.example`):
  ANTHROPIC_API_KEY  — Anthropic or OpenRouter API key
  ANTHROPIC_BASE_URL — optional; set ``https://openrouter.ai/api`` for OpenRouter
  CLAUDE_MODEL       — Anthropic id or OpenRouter slug (e.g. ``anthropic/claude-sonnet-4.6``)

Supports cooperative cancel via ``backend.job_control`` (streaming + chunk checks).
Supports Anthropic/OpenRouter prompt caching via ``CachedPrompt`` (cache_control + session_id).
"""

from __future__ import annotations

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


def _log_cache_usage(step_label: str, usage: Any, *, session_id: str | None = None) -> None:
    cache_read, cache_write, input_tokens = _usage_cache_fields(usage)
    if cache_read is None and cache_write is None and input_tokens is None:
        logger.info("%s: Claude usage unavailable (no cache metrics on response)", step_label)
        return
    hit_rate = None
    if input_tokens and cache_read is not None and input_tokens > 0:
        hit_rate = round(100.0 * cache_read / input_tokens, 1)
    logger.info(
        "%s: prompt_cache read=%s write=%s input=%s hit_rate=%s%% session=%s",
        step_label,
        cache_read if cache_read is not None else "?",
        cache_write if cache_write is not None else "?",
        input_tokens if input_tokens is not None else "?",
        hit_rate if hit_rate is not None else "?",
        session_id or "-",
    )


def _is_openrouter() -> bool:
    base = (config.ANTHROPIC_BASE_URL or "").lower()
    return "openrouter.ai" in base


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
    if prompt.session_id and _is_openrouter():
        # Sticky provider routing so cache hits are not lost to provider flips.
        extra_body["session_id"] = prompt.session_id
    if extra_body:
        kwargs["extra_body"] = extra_body
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
