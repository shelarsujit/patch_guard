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


# How far temperature is allowed to climb while trying to break a wedge, and
# how big each step is. Sampling is the lever of last resort: if the prompt
# cannot be varied into a different answer, the sampler must be.
_TEMP_STEP = 0.25
_TEMP_CEILING = 0.9


class ResilientLitellmModel(LitellmModel):
    """LitellmModel that recovers from both ways this model refuses to act.

    Two failure shapes, one underlying cause. The provider can reject a
    malformed tool call outright, or the model can return `finish_reason=stop`
    with an empty final channel and no tool call at all. Auditing 143 recorded
    baseline calls found the second shape in 76 of them -- more than half.

    Both are only fatal because the retry is byte-identical. Upstream appends a
    fixed "No tool calls found in the response" message and asks again at
    temperature 0, which reproduces the same empty reply, which appends the same
    message, until `max_consecutive_format_errors` ends the episode. The agent is
    scored as having failed to act when it was never given a different question.

    So this class varies the retry along both available axes: the message text
    escalates with each consecutive failure, and the sampling temperature climbs
    off zero. The streak resets the moment a real tool call arrives.

    This makes the BASELINE more capable, not less. It is a correction that
    works against this project's thesis, which is the safe direction for it to
    err in.
    """

    # A 400 is a verdict, not a transient fault. Without this, upstream's tenacity
    # loop re-sends the rejected request ten times before anyone sees it.
    abort_exceptions = [*LitellmModel.abort_exceptions, litellm.exceptions.BadRequestError]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._empty_streak = 0
        self._base_temperature = self.config.model_kwargs.get("temperature", 0.0)

    def _escalate(self, streak: int) -> None:
        """Raise sampling temperature so the next attempt can differ."""
        temp = min(_TEMP_CEILING, self._base_temperature + _TEMP_STEP * streak)
        self.config.model_kwargs["temperature"] = temp

    def _reset(self) -> None:
        self._empty_streak = 0
        self.config.model_kwargs["temperature"] = self._base_temperature

    def query(self, messages: list[dict[str, str]], **kwargs) -> dict:
        try:
            result = super().query(messages, **kwargs)
        except FormatError as exc:
            # Upstream raises this when the reply carried no usable tool call.
            self._empty_streak += 1
            self._escalate(self._empty_streak)
            raise self._varied(exc, self._empty_streak) from exc
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

        self._reset()
        return result

    @staticmethod
    def _varied(exc: FormatError, streak: int) -> FormatError:
        """Rebuild a FormatError whose text differs from the previous attempt.

        Upstream's message is fixed, so re-sending it asks the model the exact
        question it just declined to answer. Appending an escalating note makes
        each retry a distinct prompt.
        """
        messages = [dict(m) for m in exc.messages]
        if not messages:
            messages = [{"role": "user", "content": "", "extra": {"cost": 0.0}}]

        nudges = {
            1: ("Your last reply contained no tool call. You must respond with a "
                "bash tool call, not prose and not an empty message."),
            2: ("Again no tool call. Stop analysing and run one concrete command. "
                "If you are unsure what to do next, inspect the file: "
                "sed -n '1,200p' python_programs/<name>.py"),
            3: ("Still no tool call. Take the single smallest next action -- run "
                "the failing test, or print the file. One command."),
        }
        note = nudges.get(streak, (
            f"No tool call for {streak} turns. Emit exactly one bash command now, "
            "however small. If the fix is already written, run: "
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"))

        first = messages[0]
        first["content"] = f"{first.get('content', '')}\n\n{note}".strip()
        first.setdefault("extra", {}).setdefault("cost", 0.0)
        return FormatError(*messages)
