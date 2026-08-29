"""The worker model, wrapped so every call is recordable and replayable.

The same wrapper backs both runners, which is what makes the baseline-vs-agent
comparison fair: identical model, identical temperature, identical cassette
discipline. The only thing that differs between them is the supervision.
"""

from __future__ import annotations

import time

from patch_guard import config
from patch_guard.cassettes import Cassette


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

        # Groq's binding free-tier limit is 8k tokens/minute, not requests.
        # litellm retries on 429; this is light pacing to reduce how often
        # that path is taken.
        time.sleep(1.0)

        completion = litellm.completion(
            model=self.model,
            messages=messages,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_OUTPUT_TOKENS,
        )
        choice = completion.choices[0]
        usage = getattr(completion, "usage", None)
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
