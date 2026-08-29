"""Central configuration. Every tunable the harness and graph share lives here."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env before anything reads a provider key. litellm reads GROQ_API_KEY
# straight from the process environment, so without this a key sitting in .env
# is invisible and every live call fails authentication.
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:  # replay needs no key, so a missing dotenv must not be fatal
    pass

QUIXBUGS_DIR = REPO_ROOT / "eval" / "data" / "quixbugs"
CASES_DIR = REPO_ROOT / "eval" / "cases"
CASSETTES_DIR = REPO_ROOT / "cassettes"
TRAJECTORIES_DIR = REPO_ROOT / "trajectories"
RESULTS_DIR = REPO_ROOT / "results"
SCRATCH_DIR = REPO_ROOT / ".scratch"

# The 10 evaluated programs, in the order build_cases.py emits them.
PROGRAMS = [
    "bitcount",
    "breadth_first_search",
    "depth_first_search",
    "detect_cycle",
    "knapsack",
    "levenshtein",
    "next_permutation",
    "quicksort",
    "shortest_path_length",
    "topological_ordering",
]

# Paths the agent must never modify. python_testcases/ is the obvious one;
# json_testcases/ holds the expected outputs the parametrized tests assert
# against, so editing it is the same reward hack wearing a different hat.
# conftest.py is included because --correct would let a patch import the gold
# implementation and "pass" without fixing anything.
PROTECTED_PATHS = ["python_testcases", "json_testcases", "conftest.py"]

# The only directory a legitimate patch touches.
EDITABLE_PATHS = ["python_programs"]

# QuixBugs' own bugs include infinite loops (bitcount is `n ^= n - 1` instead of
# `n &= n - 1`), so every pytest invocation is wall-clocked. A hang is recorded
# as a failure; it is never allowed to look like a test that stopped existing.
# Raised from 20s after a loaded machine pushed legitimately-passing files past
# the per-file limit, turning "the harness ran out of time" into "the agent broke
# these tests". The cost of a generous limit is wall-clock; the cost of a tight
# one is wrong measurements.
TARGET_TEST_TIMEOUT = 20
SUITE_TIMEOUT = 120
PER_FILE_TIMEOUT = 45

# --- Worker model -----------------------------------------------------------
# Deliberately a weak open model: the whole thesis is that a cheap worker
# exhibits the three failure modes, and that deterministic gates catch them
# anyway.
#
# Served through OpenRouter rather than Groq. This is a provider change, not a
# model change -- `openai/gpt-oss-20b` is the same weights either way, and both
# runners use whichever is configured, so the same-model property the
# baseline-vs-agent comparison rests on is untouched.
#
# The reason is quota, and it is worth recording because the limits are not
# discoverable up front. Groq's free tier advertises 8000 tokens/minute and
# 1000 requests in its x-ratelimit-* headers, but enforces an additional
# 200,000 tokens/day that appears in no header and is only visible in the text
# of the rejection you get when you cross it. A full sweep needs several times
# that, so recording on Groq meant rationing across days. The same sweep on
# OpenRouter costs about three cents and is bounded by nothing but wall-clock.
DEFAULT_MODEL = "openrouter/openai/gpt-oss-20b"
MODEL = os.environ.get("PATCHGUARD_MODEL", DEFAULT_MODEL)

# Groq is kept as a documented free fallback: same model, no cost, but subject
# to the daily ceiling above. Set PATCHGUARD_MODEL to use it.
GROQ_MODEL = "groq/openai/gpt-oss-20b"

# Tokens-per-minute ceiling to pace against, by provider. Groq's is real and
# binding; OpenRouter imposes no comparable per-minute token limit, so pacing
# there would cost hours of wall-clock to respect a ceiling that is not there.
TPM_LIMITS = {"groq": 8000}


def tpm_limit(model: str | None = None) -> int | None:
    """The TPM ceiling for `model`'s provider, or None when unthrottled."""
    provider = (model or MODEL).split("/", 1)[0]
    return TPM_LIMITS.get(provider)


# OpenRouter load-balances one model id across many backends, and they do not
# behave identically. `openai/gpt-oss-20b` uses the harmony format, where the
# reasoning and the final answer are separate channels; some backends parse the
# final channel out correctly and some return only the reasoning, leaving an
# empty message with no tool call. Measured directly, same request to each:
#
#     Darkbloom       finish=stop        tool_calls=False   <- drops the answer
#     CoreWeave       finish=tool_calls  tool_calls=True
#     DeepInfra       finish=tool_calls  tool_calls=True
#     Parasail        finish=tool_calls  tool_calls=True
#     Amazon Bedrock  finish=tool_calls  tool_calls=True
#
# Unpinned, a sweep silently mixes these, and an agent scored as "failed to act"
# may only have been routed to Darkbloom that turn. Pinning is therefore a
# correctness requirement, not a preference: it removes a source of variance
# that is invisible in the results and would be baked into the cassettes.
#
# The order is tried in sequence; allow_fallbacks stays off so routing can never
# silently escape this list. A backend outage fails loudly instead.
OPENROUTER_PROVIDERS = ["DeepInfra", "CoreWeave", "Parasail"]

# Pinning is necessary but not sufficient. Even on a good backend, gpt-oss-20b
# intermittently spends an entire turn in the reasoning channel and returns an
# empty final one -- finish_reason=stop, no content, no tool call. Once a
# conversation reaches that state it stays there: at temperature 0 the retry is
# byte-identical, so it fails identically, and the episode dies on repeated
# format errors having done nothing wrong.
#
# Measured against one such wedged conversation, holding everything else fixed:
#
#     default                finish=stop        tool_calls=False
#     reasoning excluded     finish=stop        tool_calls=False
#     tool_choice=required   finish=stop        tool_calls=False
#     temperature=0.3        finish=stop        tool_calls=False
#     reasoning effort=low   finish=tool_calls  tool_calls=True    <- the fix
#
# Low effort is the only setting that reliably gets the model to stop
# deliberating and commit to an answer. It is applied to BOTH runners, so it
# changes the worker's behaviour identically on each side of the comparison and
# leaves the same-model property intact.
REASONING_EFFORT = "low"

# Seconds before a single provider call is abandoned.
#
# Not a tuning knob -- a liveness guarantee. Without it litellm will wait on a
# dead connection indefinitely, and a recording sweep that stalls looks exactly
# like a recording sweep that is working: no error, no output, no progress. One
# run sat wedged for 28 minutes on a single request before it was noticed.
# Every other slow path in this project is already wall-clocked (pytest calls,
# the agent's own shell commands); the LLM call was the last one that was not.
#
# Generous relative to observed latency, which is a few seconds per call: this
# should only ever fire on a genuinely broken connection, never on a slow one.
REQUEST_TIMEOUT = 120

# Provider-side retries for a timed-out or transient call. litellm retries
# internally; this bounds how long that can go on.
REQUEST_RETRIES = 2


def provider_routing(model: str | None = None) -> dict | None:
    """OpenRouter request extras for `model`, or None for other providers.

    Returns the backend pin and the reasoning-effort setting together: both are
    needed before this model can hold a tool-calling conversation at all.
    """
    if not (model or MODEL).startswith("openrouter/"):
        return None
    return {
        "provider": {"order": OPENROUTER_PROVIDERS, "allow_fallbacks": False},
        "reasoning": {"effort": REASONING_EFFORT},
    }
TEMPERATURE = 0.0
# gpt-oss-20b is a reasoning model: its internal reasoning is billed as
# completion tokens, so a budget sized for the visible answer alone gets
# consumed before any text is emitted (a 16-token cap returns an empty
# string, not an error).
#
# Sized from recorded usage, and revised upward once that usage was inspected.
# A first pass reasoned that a bash step spends ~140 completion tokens and the
# largest program is ~430, so 1536 looked generous. Auditing 143 recorded calls
# showed 7 of them ending at finish_reason=length with 1,079 reasoning tokens --
# the model can deliberate far past the visible answer, and a truncated reply
# carries no tool call, so it is scored as the agent failing to act.
#
# On Groq this ceiling also governed throughput, because Groq reserves
# max_tokens against its 8k tokens/minute limit at request time. On OpenRouter
# there is no such reservation and output costs $0.13/M, so 3072 adds roughly
# four hundredths of a cent per call. Truncating a reply to save that would be
# a false economy paid for in wrong measurements.
MAX_OUTPUT_TOKENS = 3072

# Documented fallback if the tokens/day ceiling bites mid-recording.
FALLBACK_MODEL = "openrouter/deepseek/deepseek-r1:free"

# "replay" (default) never touches the network -- this is what judges run.
# "record" calls the provider and writes cassettes. "none" hard-fails on a miss.
CASSETTE_MODE = os.environ.get("PATCHGUARD_CASSETTE", "replay")

# Retries the supervisor grants the worker before rejecting the patch outright.
MAX_RETRIES = 3

# Shell steps the baseline agent may take. Measured, not guessed: a smoke run
# showed ~7 steps go to legitimate exploration (read the program, the test,
# the test data, reproduce the failure) before it is ready to edit. 14 leaves
# room to edit, re-test and submit. Deliberately far more than the
# supervisor's 4 LLM calls -- where the budgets differ, the advantage belongs
# to the baseline, so the comparison cannot be accused of starving it.
BASELINE_STEP_LIMIT = 14
