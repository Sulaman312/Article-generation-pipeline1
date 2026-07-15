"""Anthropic Claude API — editorial pipeline LLM steps.

Environment (see repo `.env.example`):
  ANTHROPIC_API_KEY — required for all Claude-powered steps
  CLAUDE_MODEL       — default `claude-sonnet-4-6`

Supports cooperative cancel via ``backend.job_control`` (streaming + chunk checks).
"""

from __future__ import annotations

import logging
import time

from .. import config
from .. import job_control

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
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def chat_complete(
    system_msg: str,
    user_msg: str,
    *,
    step_label: str = "pipeline step",
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Call Claude with system + user messages; retry once after 3s on failure.

    Uses streaming so cooperative cancel can close the HTTP body promptly.
    """
    client = _get_client()
    model = config.CLAUDE_MODEL
    max_tok = max_tokens if max_tokens is not None else config.MAX_TOKENS
    temp = temperature if temperature is not None else config.TEMPERATURE

    last_exc: Exception | None = None
    for attempt in range(2):
        job_control.raise_if_cancelled()
        try:
            parts: list[str] = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tok,
                temperature=temp,
                system=system_msg,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
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
                        raise job_control.JobCancelled(
                            "Pipeline step cancelled by user"
                        )
                    parts.append(text)
            raw = "".join(parts).strip()
            if not raw:
                raise ValueError("Claude returned empty content")
            job_control.raise_if_cancelled()
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
            if attempt == 0:
                if job_control.is_cancelled():
                    raise job_control.JobCancelled(
                        "Pipeline step cancelled by user"
                    )
                time.sleep(3)
            else:
                raise RuntimeError(
                    f"Claude API call failed after retry for {step_label}: "
                    f"{type(e).__name__}: {detail}"
                ) from last_exc
    raise AssertionError("unreachable")
