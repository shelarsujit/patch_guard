"""The worker model, wrapped so every call is recordable and replayable.

The same wrapper backs both runners, which is what makes the baseline-vs-agent
comparison fair: identical model, identical temperature, identical cassette
discipline. The only thing that differs between them is the supervision.
"""

from __future__ import annotations

from patch_guard import config
from patch_guard.cassettes import Cassette
from patch_guard.ratelimit import (
    BUCKET, QuotaExhausted, estimate_prompt_tokens, is_quota_exhausted,
)


class WorkerModel:
    """A single-turn chat completion with cassette record/replay."""

    def __init__(self, case_id: str, model: str | None = None,
                 mode: str | None = None) -> None:
        self.model = model or config.MODEL
        self.cassette = Cassette(case_id, mode=mode)
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def complete(self, messages: list[dict]) -> str:
        from patch_guard.cassettes import key_for

        key = key_for(self.model, messages, config.TEMPERATURE)
        self.calls += 1

        cached = self.cassette.get(key)
        if cached is not None:
            self._account(cached)
            return cached["text"]

        if self.cassette.mode != "record":
            raise self.cassette.miss(key, messages)

        response = self._call_provider(messages)
        self.cassette.put(key, self.model, messages, response)
        self._account(response)
        return response["text"]

    # --- internals ----------------------------------------------------------

    def _account(self, response: dict) -> None:
        usage = response.get("usage") or {}
        self.tokens_in += int(usage.get("prompt_tokens") or 0)
        self.tokens_out += int(usage.get("completion_tokens") or 0)

    def _call_provider(self, messages: list[dict]) -> dict:
        import litellm

        # Groq's binding free-tier limit is 8k tokens/minute, and it reserves
        # max_tokens against that ceiling up front. Pace on the same figure the
        # server bills so requests are accepted first time instead of bouncing
        # off a 429 and sleeping for a server-chosen interval.
        reserved = estimate_prompt_tokens(messages) + config.MAX_OUTPUT_TOKENS
        BUCKET.reserve(reserved)

        try:
            completion = litellm.completion(
                model=self.model,
                messages=messages,
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_OUTPUT_TOKENS,
                # Without a timeout a dead connection stalls the sweep silently.
                timeout=config.REQUEST_TIMEOUT,
                num_retries=config.REQUEST_RETRIES,
                **({"extra_body": routing} if (routing := config.provider_routing(self.model)) else {}),
            )
        except Exception as exc:
            # Running out of the daily budget says nothing about the worker, so
            # it must not reach the graph as a failed patch attempt.
            if is_quota_exhausted(exc):
                raise QuotaExhausted(str(exc)) from exc
            raise
        choice = completion.choices[0]
        usage = getattr(completion, "usage", None)
        if usage is not None:
            BUCKET.settle(reserved, (getattr(usage, "prompt_tokens", 0) or 0)
                          + config.MAX_OUTPUT_TOKENS)
        return {
            "text": choice.message.content or "",
            "finish_reason": getattr(choice, "finish_reason", None),
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            },
        }

    def stats(self) -> dict:
        return {
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            **self.cassette.stats(),
        }
