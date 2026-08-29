"""Proactive token-per-minute pacing, shared by both runners.

Groq's free tier enforces a tokens-per-minute ceiling, and it charges the
request's `max_tokens` against that ceiling *up front* -- not the tokens the
model actually produced. A request whose prompt is 481 tokens and whose reply is
140 still reserves `481 + max_tokens`. That is why the first recording attempt
spent nearly all its wall-clock in 429 backoff.

litellm will retry a 429 for us, so pacing is not needed for correctness. It is
needed for time: reacting to a rejection wastes the round trip and then sleeps
for whatever the server dictates, whereas staying under the ceiling means the
request is accepted first time. Measured against the observed limits this is the
difference between roughly 1.4 and 2.6 accepted calls per minute.

The limiter is deliberately conservative: it reserves `max_tokens` exactly as
the server does, keeps a sliding one-minute window, and holds back a headroom
margin so that a burst of concurrent-ish calls cannot overshoot. Being slightly
too slow costs minutes; being too fast costs a rejected request plus a
server-chosen sleep.
"""

from __future__ import annotations

import threading
import time
from collections import deque

# Observed on the free tier via the x-ratelimit-limit-tokens response header.
DEFAULT_TPM = 8000

# Fraction of the ceiling we allow ourselves. The reservation is an estimate for
# the prompt half, so a margin keeps an under-estimate from turning into a 429.
HEADROOM = 0.85

WINDOW_SECONDS = 60.0


class QuotaExhausted(RuntimeError):
    """The provider's daily token budget is gone.

    This is emphatically *not* a case result. A recording sweep that hits the
    daily ceiling has learned nothing about the agent, so scoring the case would
    file a quota artefact as an agent failure -- the same class of bug that made
    a provider rejection look like a bad patch. The sweep stops instead, keeps
    whatever it recorded, and says how long until the window reopens.
    """


def is_quota_exhausted(exc: object) -> bool:
    """True when `exc` is a tokens-per-day rejection rather than a per-minute one.

    Accepts an exception or an exit-status string: mini-swe-agent swallows the
    provider error and reports it as a status, so both shapes occur.

    The daily ceiling is invisible until it is hit: the x-ratelimit-* response
    headers advertise only the per-minute token limit and the request limit, so
    the only evidence of a TPD cap is the rejection itself.
    """
    text = str(exc)
    return "rate_limit" in text and ("tokens per day" in text or "TPD" in text)


def estimate_prompt_tokens(messages) -> int:
    """Rough prompt size from message text.

    Only used to decide how long to wait, never to bill anything, so a coarse
    chars/4 estimate is adequate -- and the actual figure replaces it as soon as
    the response comes back.
    """
    chars = 0
    for msg in messages or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):  # multimodal blocks
            chars += sum(len(str(part)) for part in content)
        else:
            chars += len(str(content or ""))
    return chars // 4 + 8


class TokenBucket:
    """Sliding-window limiter over a tokens-per-minute ceiling."""

    def __init__(self, tpm: int = DEFAULT_TPM, headroom: float = HEADROOM) -> None:
        self.budget = tpm * headroom
        self._events: deque[tuple[float, float]] = deque()
        self._lock = threading.Lock()

    def _used(self, now: float) -> float:
        while self._events and now - self._events[0][0] >= WINDOW_SECONDS:
            self._events.popleft()
        return sum(tokens for _, tokens in self._events)

    def reserve(self, tokens: float) -> float:
        """Block until `tokens` fit in the window. Returns seconds slept."""
        slept = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                used = self._used(now)
                # `not self._events` lets an oversized single request through
                # rather than deadlocking on a budget it can never fit inside.
                if used + tokens <= self.budget or not self._events:
                    self._events.append((now, tokens))
                    return slept
                oldest = self._events[0][0]
            wait = max(0.25, WINDOW_SECONDS - (now - oldest) + 0.25)
            time.sleep(wait)
            slept += wait

    def settle(self, reserved: float, actual: float) -> None:
        """Correct the most recent reservation once the real usage is known."""
        with self._lock:
            for i in range(len(self._events) - 1, -1, -1):
                ts, tokens = self._events[i]
                if tokens == reserved:
                    self._events[i] = (ts, actual)
                    return


class _NullBucket:
    """No-op limiter for providers without a per-minute token ceiling.

    Pacing against a limit that does not exist would spend hours of wall-clock
    buying nothing, so the pacer disappears rather than being merely generous.
    """

    def reserve(self, tokens: float) -> float:
        return 0.0

    def settle(self, reserved: float, actual: float) -> None:
        return None


def bucket_for(model: str | None = None):
    """The limiter appropriate to `model`'s provider."""
    from patch_guard import config

    tpm = config.tpm_limit(model)
    return TokenBucket(tpm=tpm) if tpm else _NullBucket()


#: Process-wide bucket. Both runners talk to the same provider account, so the
#: ceiling is shared and the limiter must be too.
BUCKET = bucket_for()
