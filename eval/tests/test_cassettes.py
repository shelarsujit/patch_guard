"""Cassette record/replay behaviour.

The reproducibility claim rests on these: replay must be exact, a miss must be
loud, and no credential may ever reach a committed file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from patch_guard.cassettes import Cassette, CassetteMiss, key_for  # noqa: E402
from patch_guard.model import WorkerModel  # noqa: E402

MESSAGES = [{"role": "user", "content": "fix the bug"}]
RESPONSE = {"text": "patched", "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def test_key_is_stable_and_order_independent():
    a = key_for("m", MESSAGES, 0.0)
    b = key_for("m", [{"content": "fix the bug", "role": "user"}], 0.0)
    assert a == b, "key must not depend on dict key ordering"


def test_key_changes_with_conversation_position():
    """A multi-step trajectory replays in order only if each step's full
    message history is part of the key."""
    one = key_for("m", MESSAGES, 0.0)
    two = key_for("m", MESSAGES + [{"role": "assistant", "content": "x"}], 0.0)
    assert one != two


def test_record_then_replay_round_trips(tmp_path):
    rec = Cassette("case", mode="record", root=tmp_path)
    key = key_for("m", MESSAGES, 0.0)
    rec.put(key, "m", MESSAGES, RESPONSE)

    replay = Cassette("case", mode="replay", root=tmp_path)
    assert replay.get(key) == RESPONSE
    assert replay.stats()["hits"] == 1


def test_replay_miss_is_loud(tmp_path):
    replay = Cassette("case", mode="replay", root=tmp_path)
    key = key_for("m", MESSAGES, 0.0)
    assert replay.get(key) is None
    with pytest.raises(CassetteMiss, match="No recording"):
        raise replay.miss(key, MESSAGES)


def test_worker_replays_without_network(tmp_path, monkeypatch):
    """The judge path: no key, no network, exact reproduction."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    seed = Cassette("case", mode="record", root=tmp_path)
    seed.put(key_for("groq/openai/gpt-oss-20b", MESSAGES, 0.0),
             "groq/openai/gpt-oss-20b", MESSAGES, RESPONSE)

    worker = WorkerModel("case", model="groq/openai/gpt-oss-20b", mode="replay")
    worker.cassette = Cassette("case", mode="replay", root=tmp_path)

    def explode(*a, **k):
        raise AssertionError("replay must never call the provider")

    monkeypatch.setattr(worker, "_call_provider", explode)

    assert worker.complete(MESSAGES) == "patched"
    assert worker.tokens_in == 11 and worker.tokens_out == 7


def test_worker_miss_raises_instead_of_calling_provider(tmp_path, monkeypatch):
    worker = WorkerModel("case", mode="replay")
    worker.cassette = Cassette("case", mode="replay", root=tmp_path)
    monkeypatch.setattr(worker, "_call_provider",
                        lambda *a, **k: pytest.fail("provider called during replay"))
    with pytest.raises(CassetteMiss):
        worker.complete(MESSAGES)


def test_credentials_are_redacted_before_writing(tmp_path):
    """Second line of defence -- keys must not reach a committed file even if
    a caller passes them through by mistake."""
    rec = Cassette("case", mode="record", root=tmp_path)
    leaky_messages = [{"role": "user", "content": "auth: Bearer sk-abcdefghijklmnopqrstuvwxyz123456"}]
    leaky_response = {"text": "token gsk_abcdefghijklmnopqrstuvwxyz123456 leaked"}
    key = key_for("m", leaky_messages, 0.0)
    rec.put(key, "m", leaky_messages, leaky_response)

    written = (tmp_path / "case").glob("*.json")
    blob = json.dumps([json.loads(p.read_text(encoding="utf-8")) for p in written])
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in blob
    assert "gsk_abcdefghijklmnopqrstuvwxyz123456" not in blob
    assert "<redacted>" in blob


def test_a_cassette_never_serves_one_model_the_other_model_s_run(tmp_path):
    """Cross-model contamination is silent and total.

    The sequential fallback replays "the next recorded decision, in recorded
    order", which is what makes a shell-driving agent replayable at all. It also
    means that without a model check it will happily hand a gpt-oss-120b sweep
    the decisions gpt-oss-20b made -- and the sweep succeeds, writes results, and
    reports numbers.

    That happened: a 120b capability run produced numbers identical to the 20b
    run, case for case, including which impossible variants were cheated on.
    Only one cassette in the whole repository had actually been recorded under
    the 120b model. The identical numbers were the only symptom.
    """
    from patch_guard.cassettes import Cassette

    c = Cassette("xmodel", mode="record", root=tmp_path)
    msgs = [{"role": "user", "content": "fix it"}]
    c.put(key_for("model-a", msgs, 0.0), "model-a", msgs, {"text": "answer from A"})

    replay = Cassette("xmodel", mode="replay", root=tmp_path)
    assert replay.get_sequential("model-a") is not None, "same model still replays"

    other = Cassette("xmodel", mode="replay", root=tmp_path)
    assert other.get_sequential("model-b") is None, \
        "a different model must miss rather than inherit another model's run"
