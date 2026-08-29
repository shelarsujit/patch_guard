"""Tests for the tokens-per-minute pacer.

The limiter only ever costs wall-clock, never correctness, so these tests are
about the two ways it could be quietly wrong: letting a burst through (which
puts us back in 429 backoff and doubles the sweep time) and deadlocking on a
request larger than the whole budget (which would hang a recording run
overnight with no error).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from patch_guard import ratelimit  # noqa: E402


@pytest.fixture
def fast_window(monkeypatch):
    """Shrink the window so the blocking path is testable in milliseconds."""
    monkeypatch.setattr(ratelimit, "WINDOW_SECONDS", 0.2)
    return ratelimit.TokenBucket(tpm=1000, headroom=1.0)


def test_calls_under_the_ceiling_never_sleep(fast_window):
    assert fast_window.reserve(400) == 0.0
    assert fast_window.reserve(400) == 0.0


def test_exceeding_the_ceiling_blocks(fast_window):
    fast_window.reserve(900)
    assert fast_window.reserve(400) > 0.0, "the second call must wait for the window"


def test_an_oversized_request_is_not_a_deadlock(fast_window):
    """A single request bigger than the entire budget must still go out.

    Blocking forever would hang a recording sweep silently; the provider
    rejecting it is a far better failure, because it says why.
    """
    assert fast_window.reserve(5000) == 0.0


def test_settle_replaces_the_estimate_with_the_measurement(fast_window):
    fast_window.reserve(900)
    fast_window.settle(900, 100)
    # With the reservation corrected down, the next call fits without waiting.
    assert fast_window.reserve(400) == 0.0


def test_prompt_estimate_grows_with_the_prompt():
    small = ratelimit.estimate_prompt_tokens([{"role": "user", "content": "hi"}])
    large = ratelimit.estimate_prompt_tokens([{"role": "user", "content": "x" * 4000}])
    assert small < large
    assert 900 < large < 1100, "chars/4 is the intended rough scale"


def test_estimate_survives_non_string_content():
    """litellm messages carry list content for multimodal and None for tool
    calls; an estimator that raises here would break the live path only."""
    assert ratelimit.estimate_prompt_tokens([{"role": "assistant", "content": None}]) > 0
    assert ratelimit.estimate_prompt_tokens(
        [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]) > 0


# --- Daily quota vs. agent failure ------------------------------------------

_TPD = ('litellm.RateLimitError: GroqException - {"error":{"message":"Rate limit '
        'reached for model `openai/gpt-oss-20b` ... on tokens per day (TPD): '
        'Limit 200000, Used 198826, Requested 3836","code":"rate_limit_exceeded"}}')
_TPM = ('litellm.RateLimitError: GroqException - {"error":{"message":"Rate limit '
        'reached for model `openai/gpt-oss-20b` ... on tokens per minute (TPM): '
        'Limit 8000, Used 4967, Requested 5191","code":"rate_limit_exceeded"}}')


def test_daily_ceiling_is_recognised():
    """The TPD cap is invisible in the x-ratelimit-* headers, which advertise
    only TPM and requests. The rejection text is the only evidence there is."""
    assert ratelimit.is_quota_exhausted(_TPD)
    assert ratelimit.is_quota_exhausted(RuntimeError(_TPD))


def test_per_minute_limit_is_not_a_quota_stop():
    """A TPM rejection is transient and litellm retries through it. Confusing
    the two would abandon a sweep that was merely going too fast."""
    assert not ratelimit.is_quota_exhausted(_TPM)


def test_ordinary_failures_are_not_quota_stops():
    assert not ratelimit.is_quota_exhausted(ValueError("boom"))
    assert not ratelimit.is_quota_exhausted("")


def test_quota_exhaustion_stops_the_sweep_without_scoring_the_case(tmp_path):
    """The validity property: a case abandoned to the daily ceiling must not
    appear in the results at all. Scoring it would file a billing artefact as
    an agent failure and quietly deflate the headline number."""
    from eval import harness

    cases = harness.load_cases(["quixbugs__quicksort", "quixbugs__bitcount"])
    assert len(cases) == 2

    class _QuotaRunner:
        name = "quotatest"

        def __init__(self):
            self.seen = 0

        def __call__(self, case, ws):
            self.seen += 1
            if self.seen == 1:
                return {"done_claim": False, "exit_status": "Submitted"}
            raise ratelimit.QuotaExhausted(_TPD)

    runner = _QuotaRunner()
    results, summary = harness.run(runner, cases, tmp_path / "out.jsonl",
                                   scratch=tmp_path / "scratch", verbose=False)

    assert runner.seen == 2, "the sweep must have attempted the second case"
    assert len(results) == 1, "but the abandoned case must not be scored"
    # load_cases returns cases in a stable order that is not the argument order,
    # so assert against the order actually swept rather than a hard-coded id.
    assert results[0].case_id == cases[0]["case_id"]
    assert summary.n_standard == 1, "the summary must not count the abandoned case"
