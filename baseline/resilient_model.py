"""A LitellmModel that recovers from Groq's malformed-tool-call rejection.

`gpt-oss-20b` was trained against an `apply_patch` tool that takes a heredoc
patch body. When it wants to rewrite a file it reaches for that format even
though the only declared tool is bash, and the heredoc lands inside a JSON
tool-call argument. Groq rejects the whole request with HTTP 400
`tool_use_failed`, so the agent never gets an observation back and the episode
dies on a provider error rather than on anything the agent did wrong.

Upstream already has the right recovery mechanism: `FormatError`, which
`DefaultAgent.run` catches and whose messages it *appends to the conversation*
(default.py:114) before letting the agent try again. That append is the load
bearing part -- see below.

Two things have to be true for that path to work, and both are handled here.

1. The rejection must not be retried inside the model layer. `LitellmModel.query`
   calls `_query` inside a tenacity loop with `stop_after_attempt(10)` and
   exponential backoff, and `BadRequestError` is not in upstream's
   `abort_exceptions`. Overriding `_query` therefore fails silently-but-loudly:
   tenacity swallows the FormatError and re-sends the identical request ten
   times over ~4 minutes. So the override belongs on `query`, and
   `BadRequestError` is added to `abort_exceptions` so the futile retries stop.
   Retrying a 400 is pointless in any case -- it is a deterministic rejection,
   not a transient fault.

2. The retry must not be byte-identical. The worker runs at temperature 0, so
   re-sending the same messages reproduces the same invalid generation forever.
   Returning a FormatError works precisely because DefaultAgent appends the hint
   as a new user turn: the next request has a different prompt, and can produce a
   different answer.

This does not make the agent smarter -- it still has to produce a valid edit,
and `max_consecutive_format_errors` still ends the episode. It removes a harness
artefact that would otherwise be scored as an agent failure.
"""

from __future__ import annotations

import litellm
from minisweagent.exceptions import FormatError
from minisweagent.models.litellm_model import LitellmModel

# Groq returns this code both for unparseable tool-call JSON and for a tool the
# request never declared.
_TOOL_USE_FAILED = "tool_use_failed"

_RETRY_HINT = (
    "Your last tool call was rejected by the API before it ran: its arguments "
    "were not valid JSON. This happens when a heredoc or an `apply_patch` block "
    "is placed inside the command argument.\n\n"
    "There is no `apply_patch` tool here. The only tool is bash, and the command "
    "must be a single line.\n\n"
    "To rewrite a file, use printf with one quoted argument per line:\n"
    "  printf '%s\\n' 'def add(a, b):' '    return a + b' > python_programs/add.py\n"
    "To change one line in place, use sed:\n"
    "  sed -i 's/old/new/' python_programs/add.py\n"
)


class ResilientLitellmModel(LitellmModel):
    """LitellmModel that converts provider tool-call rejections into FormatError."""

    # A 400 is a verdict, not a transient fault. Without this, upstream's tenacity
    # loop re-sends the rejected request ten times before anyone sees it.
    abort_exceptions = [*LitellmModel.abort_exceptions, litellm.exceptions.BadRequestError]

    def query(self, messages: list[dict[str, str]], **kwargs) -> dict:
        try:
            return super().query(messages, **kwargs)
        except litellm.exceptions.BadRequestError as exc:
            # ContextWindowExceededError subclasses BadRequestError; it is a real
            # failure and must keep propagating.
            if _TOOL_USE_FAILED not in str(exc):
                raise
            # FormatError takes *messages as varargs, so the dict is passed
            # bare. Wrapping it in a list makes `e.messages[0]` a list, and
            # DefaultAgent calls `.get("extra")` on it (default.py:102).
            raise FormatError(
                {
                    "role": "user",
                    "content": _RETRY_HINT,
                    # DefaultAgent reads extra["cost"] when accounting for a
                    # FormatError, so the key must exist. The rejected call
                    # was never billed.
                    "extra": {"cost": 0.0, "tool_call_rejected": True},
                }
            ) from exc
