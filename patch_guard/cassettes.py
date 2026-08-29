"""Recorded LLM decisions, so a judge reproduces the exact run at $0.

Hooked at the ``litellm.completion()`` call rather than at the HTTP layer.
Both runners -- mini-swe-agent and the LangGraph supervisor -- route through
litellm, so one hook covers both. HTTP-level recording (VCR.py and friends)
would also bake provider auth headers into committed files and break whenever
litellm changes its request shape.

Only the *model's decisions* are replayed. Tools still run for real against the
filesystem, and pytest still really executes -- so a replayed trajectory is an
honest one. The agent's choices are fixed; the consequences are recomputed.

Modes (``PATCHGUARD_CASSETTE``):
    replay  default. Never touches the network. A miss is a loud error.
    record  call the provider, persist the response, then behave like replay.
    none    replay with no fallback of any kind (CI).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from patch_guard import config


class CassetteMiss(RuntimeError):
    """Raised when replay has no recording for a request.

    Deliberately fatal. A cassette layer that silently fell through to the
    network would make a "reproduced at $0" claim untrue without anyone
    noticing.
    """


# Belt-and-braces: these must never reach a committed file. The recorder only
# ever persists messages and response text, so this is a second line of defence
# against a future change piping request kwargs in wholesale.
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|gsk_[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,})"
)


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub("<redacted>", text)


def key_for(model: str, messages: list[dict], temperature: float) -> str:
    """Stable content hash of the request.

    Keyed on the full message list, so the same prompt in a different
    conversational position is a different recording -- which is what makes a
    multi-step trajectory replay in order.
    """
    payload = json.dumps(
        {"model": model, "temperature": temperature, "messages": messages},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Cassette:
    """Read/write access to one case's recorded decisions."""

    def __init__(self, case_id: str, mode: str | None = None,
                 root: Path | None = None) -> None:
        self.case_id = case_id
        self.mode = mode or config.CASSETTE_MODE
        self.dir = (root or config.CASSETTES_DIR) / case_id
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def _path(self, key: str) -> Path:
        return self.dir / f"{key[:16]}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        # Guard against a short-hash collision between two different prompts.
        if record.get("key") != key:
            return None
        self.hits += 1
        return record["response"]

    def put(self, key: str, model: str, messages: list[dict], response: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "case_id": self.case_id,
            "model": model,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "messages": json.loads(_redact(json.dumps(messages, ensure_ascii=False))),
            "response": json.loads(_redact(json.dumps(response, ensure_ascii=False))),
        }
        self._path(key).write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.writes += 1

    def miss(self, key: str, messages: list[dict]) -> CassetteMiss:
        self.misses += 1
        preview = (messages[-1].get("content", "") if messages else "")[:200]
        return CassetteMiss(
            f"No recording for case {self.case_id!r} (key {key[:16]}).\n"
            f"  mode={self.mode}  dir={self.dir}\n"
            f"  last message: {preview!r}\n"
            f"Re-record with PATCHGUARD_CASSETTE=record (needs GROQ_API_KEY), "
            f"or check that the prompt has not drifted since recording."
        )

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "writes": self.writes}
