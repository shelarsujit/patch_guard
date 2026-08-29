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
TARGET_TEST_TIMEOUT = 20
SUITE_TIMEOUT = 90
PER_FILE_TIMEOUT = 20

# --- Worker model -----------------------------------------------------------
# Groq free tier, read from the x-ratelimit-* response headers rather than
# assumed: 8000 tokens/minute and 1000 requests, with no tokens-per-day header
# in evidence. The binding constraint is therefore throughput, not a daily
# ceiling -- see patch_guard/ratelimit.py. Deliberately a weak open model: the
# whole thesis is that a cheap worker exhibits the three failure modes, and
# that deterministic gates catch them anyway.
DEFAULT_MODEL = "groq/openai/gpt-oss-20b"
MODEL = os.environ.get("PATCHGUARD_MODEL", DEFAULT_MODEL)
TEMPERATURE = 0.0
# gpt-oss-20b is a reasoning model: its internal reasoning is billed as
# completion tokens, so a budget sized for the visible answer alone gets
# consumed before any text is emitted (a 16-token cap returns an empty
# string, not an error).
#
# The upper bound matters for throughput, not just truncation: Groq reserves
# max_tokens against the 8k tokens/minute ceiling at request time, whatever the
# reply actually costs. At 4096 a call reserved ~4.6k and the sweep managed
# under 1.5 accepted calls a minute. Measured usage is far below that -- a bash
# tool-call step spends ~140 completion tokens, and the largest program in the
# set is ~430 tokens, so even a full-file rewrite leaves ~1.1k here for
# reasoning. Sized from those measurements rather than from caution.
MAX_OUTPUT_TOKENS = 1536

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
