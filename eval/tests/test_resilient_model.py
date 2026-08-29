"""Regression tests for the baseline's provider-rejection recovery.

These exist because the first version of `resilient_model.py` looked correct,
imported cleanly, and was completely inert. Two independent bugs hid behind a
plausible-looking file, and neither was visible without driving the real
`DefaultAgent`:

1. The override was on `_query`, which upstream calls *inside* a tenacity retry
   loop (litellm_model.py:82). The FormatError was swallowed and the identical
   request re-sent ten times with exponential backoff -- so a mangled tool call
   cost ten live API calls and about four minutes, then killed the episode
   anyway.
2. `FormatError` takes `*messages` as varargs, so passing a list made
   `e.messages[0]` a list; `DefaultAgent` calls `.get("extra")` on it
   (default.py:102) and would have crashed as soon as bug 1 was fixed.

A harness bug that turns provider noise into a scored agent failure corrupts the
headline number quietly, so it is worth a test that fails loudly.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import litellm
import pytest
from minisweagent.agents.default import DefaultAgent
from minisweagent.exceptions import FormatError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from baseline.bash_env import BashEnvironment  # noqa: E402
from baseline.resilient_model import ResilientLitellmModel  # noqa: E402

_REJECTION = ('{"error":{"message":"Failed to parse tool call arguments as JSON",'
              '"type":"invalid_request_error","code":"tool_use_failed"}}')


def _rejection() -> litellm.exceptions.BadRequestError:
    return litellm.exceptions.BadRequestError(
        message=_REJECTION, model="groq/openai/gpt-oss-20b", llm_provider="groq")


def _submit_response() -> litellm.ModelResponse:
    return litellm.ModelResponse(**{
        "model": "groq/openai/gpt-oss-20b",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps(
                            {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}),
                    },
                }],
            },
        }],
    })


@pytest.fixture
def model(monkeypatch):
    return ResilientLitellmModel(model_name="groq/openai/gpt-oss-20b",
                                 cost_tracking="ignore_errors")


def test_rejection_is_not_retried_by_the_model_layer(model, monkeypatch):
    """A 400 is a verdict, not a transient fault.

    Upstream's tenacity loop would re-send it ten times. At temperature 0 the
    model reproduces the same invalid generation every time, so those retries
    could never succeed -- they only burned quota and wall-clock.
    """
    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1
        raise _rejection()

    monkeypatch.setattr(litellm, "completion", fake_completion)

    with pytest.raises(FormatError):
        model.query([{"role": "user", "content": "hi"}])

    assert calls["n"] == 1, "the rejection must abort the retry loop immediately"


def test_format_error_payload_matches_what_the_agent_reads(model, monkeypatch):
    """DefaultAgent reads `e.messages[0]["extra"]["cost"]` (default.py:102)."""
    monkeypatch.setattr(litellm, "completion", lambda **kw: (_ for _ in ()).throw(_rejection()))

    with pytest.raises(FormatError) as exc:
        model.query([{"role": "user", "content": "hi"}])

    message = exc.value.messages[0]
    assert isinstance(message, dict), "messages are varargs, not a nested list"
    assert message["role"] == "user"
    assert message["extra"]["cost"] == 0.0, "the rejected call was never billed"


def test_agent_recovers_and_still_submits(model, monkeypatch):
    """The whole point: a rejection costs one turn, not the episode.

    Recovery depends on the hint being *appended to the conversation* -- at
    temperature 0 an identical prompt yields an identical rejection, so the
    changed prompt is what makes the retry able to differ.
    """
    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rejection()
        return _submit_response()

    monkeypatch.setattr(litellm, "completion", fake_completion)

    with tempfile.TemporaryDirectory() as tmp:
        agent = DefaultAgent(
            model, BashEnvironment(cwd=tmp, timeout=30),
            step_limit=5, cost_limit=0.0, max_consecutive_format_errors=3,
            system_template="sys", instance_template="{{task}}")
        result = agent.run(task="fix it")

    assert result["exit_status"] == "Submitted"
    assert calls["n"] == 2, "one wasted turn, not ten"
    assert any("rejected by the API" in str(m.get("content", "")) for m in agent.messages), \
        "the hint must reach the conversation, or the retry is byte-identical"


def test_unrelated_bad_requests_still_propagate(model, monkeypatch):
    """Only `tool_use_failed` is a format problem. A context-window overflow is
    a real failure and must not be disguised as one."""
    def fake_completion(**kwargs):
        raise litellm.exceptions.ContextWindowExceededError(
            message="prompt is too long", model="m", llm_provider="groq")

    monkeypatch.setattr(litellm, "completion", fake_completion)

    with pytest.raises(litellm.exceptions.BadRequestError):
        model.query([{"role": "user", "content": "hi"}])
