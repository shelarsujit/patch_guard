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
