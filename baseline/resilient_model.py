"""A LitellmModel that recovers from Groq's malformed-tool-call rejection.

`gpt-oss-20b` writes multi-line file edits as raw heredocs. When those are
emitted inside a JSON tool-call argument the JSON is invalid, and Groq rejects
the whole request with HTTP 400 `tool_use_failed` -- so the agent never gets an
observation back and the episode dies on a provider error rather than on
anything the agent did wrong.

Upstream already has the right recovery mechanism for a malformed reply:
`FormatError`, which `DefaultAgent.run` catches, feeds back to the model as a
message, and counts against `max_consecutive_format_errors`. This subclass
simply routes the provider-side rejection into that existing path, so a
mangled tool call costs the agent one turn instead of the whole run.

This does not make the agent smarter -- it still has to produce a valid edit,
and repeated failures still end the episode. It removes a harness artefact that
would otherwise be scored as an agent failure.
"""

from __future__ import annotations

import litellm
from minisweagent.exceptions import FormatError
from minisweagent.models.litellm_model import LitellmModel

# Groq returns this code both for unparseable tool-call JSON and for a tool the
# request never declared.
_TOOL_USE_FAILED = "tool_use_failed"

_RETRY_HINT = (
    "Your last tool call was rejected by the API because its arguments were not "
    "valid JSON. This usually happens when a multi-line heredoc is placed inside "
    "the command argument.\n\n"
    "Retry with a single self-contained shell command. To rewrite a file, prefer "
    "a one-line form such as:\n"
    "  printf '%s\\n' 'line one' 'line two' > path/to/file.py\n"
    "or use sed for a targeted change. Do not use <<'EOF' heredocs."
)


class ResilientLitellmModel(LitellmModel):
    """LitellmModel that converts provider tool-call rejections into FormatError."""

    def _query(self, messages: list[dict[str, str]], **kwargs):
        try:
            return super()._query(messages, **kwargs)
        except litellm.exceptions.BadRequestError as exc:
            if _TOOL_USE_FAILED not in str(exc):
                raise
            raise FormatError(
                [
                    {
                        "role": "user",
                        "content": _RETRY_HINT,
                        # DefaultAgent reads extra["cost"] when accounting for a
                        # FormatError, so the key must exist. The rejected call
                        # was never billed.
                        "extra": {"cost": 0.0, "tool_call_rejected": True},
                    }
                ]
            ) from exc
