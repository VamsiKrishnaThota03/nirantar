"""Claude client for the reasoning agents, with a deterministic fallback.

Design rule that matters more than the client code: **the model advises, the
rules decide anything that can hurt someone.** Every agent in this system has
a deterministic core that produces a complete, safe answer on its own. The
language model is layered on top to do what rules are bad at -- weighing
messy barriers, writing in a patient's own dialect, explaining a decision to
a block medical officer in prose. Where the model's output would change a
clinically material ordering, ``bounded_*`` helpers clamp it and record the
override on the plan.

This means the system degrades to "slightly less eloquent" when the API key
is absent, the network is down, or the model returns nonsense -- never to
"unsafe" and never to "offline". A village health worker's tablet does not
get to depend on an API being up.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import get_settings

# Set for work that must not spend tokens -- bulk backlog simulation, tests,
# anything triggered by an anonymous caller in a public demo. The pipeline
# then runs entirely on its deterministic core, which is the point of having
# one.
FORCE_DETERMINISTIC: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "nirantar_force_deterministic", default=False
)

log = logging.getLogger("nirantar.llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class LLMUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    fallbacks: int = 0
    _window_start: float = field(default_factory=time.monotonic)
    _window_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "failures": self.failures,
            "deterministic_fallbacks": self.fallbacks,
        }


USAGE = LLMUsage()


class RateLimited(RuntimeError):
    pass


def _check_budget(max_per_hour: int) -> None:
    now = time.monotonic()
    if now - USAGE._window_start > 3600:
        USAGE._window_start = now
        USAGE._window_calls = 0
    if USAGE._window_calls >= max_per_hour:
        raise RateLimited(
            f"LLM budget of {max_per_hour} calls/hour exhausted; falling back "
            "to deterministic reasoning."
        )
    USAGE._window_calls += 1


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


async def complete_json(
    *,
    system: str,
    prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    retries: int = 1,
) -> dict[str, Any] | None:
    """Ask Claude for a JSON object. Returns None if unavailable or unusable.

    Returning None rather than raising is deliberate: every caller already
    has a deterministic answer in hand and treats the model as an optional
    improvement.
    """
    settings = get_settings()
    if FORCE_DETERMINISTIC.get() or not settings.llm_enabled:
        USAGE.fallbacks += 1
        return None
    try:
        _check_budget(settings.llm_max_calls_per_hour)
    except RateLimited as exc:
        log.warning("%s", exc)
        USAGE.fallbacks += 1
        return None

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key or "",
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
                response = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            if response.status_code >= 400:
                # 401/400 are configuration problems; retrying will not help.
                log.warning("Claude rejected the request: HTTP %s", response.status_code)
                USAGE.failures += 1
                USAGE.fallbacks += 1
                return None
            body = response.json()
            usage = body.get("usage") or {}
            USAGE.calls += 1
            USAGE.input_tokens += int(usage.get("input_tokens") or 0)
            USAGE.output_tokens += int(usage.get("output_tokens") or 0)
            text = "".join(
                block.get("text", "")
                for block in body.get("content", [])
                if block.get("type") == "text"
            )
            parsed = _extract_json(text)
            if parsed is None:
                last_error = "unparseable response"
                continue
            return parsed
        except (httpx.HTTPError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(0.4 * (attempt + 1))

    log.warning("LLM call failed (%s); using deterministic path", last_error)
    USAGE.failures += 1
    USAGE.fallbacks += 1
    return None


# --- guardrails ------------------------------------------------------------


def bounded_float(
    value: Any, *, low: float, high: float, default: float
) -> tuple[float, str | None]:
    """Clamp a model-supplied number into a clinically defensible range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default, "non-numeric value replaced with deterministic default"
    if number < low or number > high:
        clamped = min(high, max(low, number))
        return clamped, f"value {number:.3f} clamped to [{low}, {high}]"
    return number, None


def bounded_text(value: Any, *, max_chars: int, default: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    cleaned = value.strip()
    return cleaned[:max_chars]


def bounded_choice(value: Any, *, allowed: set[str], default: str) -> tuple[str, str | None]:
    if isinstance(value, str) and value in allowed:
        return value, None
    return default, f"disallowed choice {value!r} replaced with {default!r}"
