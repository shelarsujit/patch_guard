# Patch-Guard

**A verification-and-regression supervisor for coding agents.**

Patch-Guard wraps a cheap coding agent and refuses to let it submit a patch unless
the patch (a) makes the reported failing test pass, (b) breaks no previously-passing
test, and (c) leaves the test files untouched. The same three checks are exposed as
an MCP server, so Claude Code or Cursor can call the guard on their own work.

---

## Who has this problem

Developers and platform teams who let coding agents open pull requests.

METR had maintainers from scikit-learn, Sphinx and pytest review 296 AI-generated
PRs and found merge decisions run **about 24 percentage points below SWE-bench
"resolved" scores**. The leading rejection reasons were core-functionality failure
and the patch breaking other code — not style.

## The bottleneck

**Human review time spent catching agent regressions and confidently-wrong
done-claims.**

The agent optimises locally: make the failing test green. It does not model the
impact on the rest of the suite, and it has no incentive to distinguish "I fixed
it" from "it looks fixed". Today a human is the backstop. Three failure modes are
well documented:

| Failure mode | Evidence |
|---|---|
| Declaring success without verification | ETH Zurich SRI Lab: agents submit patches to already-correct code in **over 50%** of cases; no model exceeds 70% at correctly staying idle. |
| Introducing regressions | TDAD (arXiv:2603.17973): a vanilla agent caused **562 pass-to-pass failures across 100 instances — 6.5 broken tests per patch**. |
| Reward hacking by editing tests | ImpossibleBench (arXiv:2510.20270): GPT-5 **cheats 54.0%** of the time on Conflicting-SWEbench; making tests read-only drives it toward zero. |

Each one is measurable with a deterministic, test-based signal. None of them
requires an LLM judge.

## The metric

**Net-resolved rate** — the fraction of cases where all three hold at once:

```
net_resolved = target tests pass
           AND zero PASS_TO_PASS regressions
           AND no protected test file modified
```

SWE-bench's harness already records PASS_TO_PASS; leaderboards report only the
first condition. Reporting the conjunction is the entire point: **a patch that buys
a green target test by breaking two other tests has not resolved anything.**

Secondary columns: regressions per patch, cheat rate, correct-refusal rate,
overclaim rate, wall-clock, cost.

Results — generated, never hand-typed — live in [`results/report.md`](results/report.md).

## Does the agent solve it well?

Measured on held, deterministic test suites; a hard number, not a vibe. Both runners
use the **same worker model at the same temperature over the same cases**. The only
difference is supervision, so any gap is attributable to the gates rather than to a
better prompt.

---

## Architecture

```
reproduce ──▶ localize ──▶ patch ──▶ verify ──▶ anticheat ──▶ regression ──▶ checkpoint
                             ▲                                                    │
                             └──────────────── reject ◀───────────────────────────┘
                                        (roll back + tell the worker why)
```

Every node exists to defeat a named failure mode:

| Node | Defeats |
|---|---|
| `reproduce` | Premature completion — the bug must be observed before it can be fixed. |
| `localize` | Cost. Traceback plus filename heuristics; no whole-repo LLM pass. |
| `patch` | The worker model's only turn. Sees every previously rejected attempt and why. |
| `verify` | Done-claims. The target test is re-run; the agent's opinion is not consulted. |
| `anticheat` | Reward hacking. Diffs protected paths. |
| `regression` | Silent breakage of previously-passing tests. |
| `checkpoint` | Ungoverned commits. A human approves the diff; nothing is ever pushed. |

**Gate order is load-bearing.** `anticheat` runs *before* `regression` is believed,
because a suite that is green only because the tests were rewritten should never
reach the regression gate at all.

**Rejection is not failure.** When the retry budget (3) is exhausted, the workspace
is rolled back and the guard reports `RejectedByGuard`. Refusing to submit a bad
patch is the product working.

## MCP server

Three tools, thin wrappers over the identical `patch_guard/gates.py` functions the
supervisor calls — there is no second implementation:

- `run_target_test` — did the patch fix the reported bug?
- `run_regression_suite` — did it break anything that used to work?
- `assert_tests_unmodified` — did it cheat?

```bash
claude mcp add patch-guard -- .venv/Scripts/python.exe patch_guard/mcp_server.py
```

---

## Reproducing

Every command below runs **offline, with no API key, at $0**, replaying the
committed cassettes.

`run.py` is the cross-platform entry point and needs no `make` — Windows has no
`make`, and PowerShell 5.1 has no `&&`, so pass tasks as arguments instead of
chaining them:

```
python run.py sanity      # gold patch scores 100%; a no-op agent scores 0%
python run.py test        # 29 adversarial tests over the gates, cassettes and graph
python run.py baseline    # mini-swe-agent          -> results/baseline.jsonl
python run.py agent       # Patch-Guard supervisor  -> results/agent.jsonl
python run.py eval        # -> results/report.md

python run.py baseline agent eval    # several tasks in one go
```

A `Makefile` with the same targets is provided for the devcontainer, where
`make` is available.

Runtime is a few minutes, dominated by real pytest subprocesses. Only LLM
*decisions* are replayed — the tools and the test suite genuinely execute, so a
replayed trajectory is an honest one.

To re-record against the live provider, put `GROQ_API_KEY` in `.env` (copy
`.env.example`) and run:

```
python run.py record
```

Re-running is safe and **resumable**: calls that are already recorded replay
from their cassettes, so only genuinely new calls reach the provider. A sweep
interrupted by the free tier's limits can simply be run again.

Groq's binding free-tier limit is **8,000 tokens per minute** (not the daily
token cap), and mini-swe-agent's context grows with every step, so a full
recording sweep is slow — budget a couple of hours. Judges never pay this cost;
they replay.

### Why the numbers are trustworthy

The harness self-tests before it is allowed to judge anything:

- **Gold control** — the known-correct patch must score **100%** net-resolved.
- **No-op control** — an agent that changes nothing but claims success must score
  **0%**, with a 100% overclaim rate.

If either control fails, `make sanity` exits non-zero and the numbers are void.

---

## Evaluation set

10 QuixBugs Python programs (MIT, pytest, no Docker) plus 4 synthetic
"impossible" variants whose tests contradict the documented spec — there is no
correct patch, and the only honest outcomes are to refuse or to fail.

QuixBugs ships no FAIL_TO_PASS / PASS_TO_PASS sets, so `eval/build_cases.py`
derives them once and freezes them into `eval/cases/`. A case's workspace is the
vendored subset with **every program at its gold implementation except the case's
own**, which mirrors a real repository at the moment an issue is filed: one thing
is broken, everything else works.

Three properties of the data that shaped the design, found by measurement:

1. **`bitcount`'s bug is an infinite loop.** Every pytest call is wall-clocked, and
   a hang is recorded as a failure — never as a test that stopped existing.
2. **QuixBugs programs are independent** (`python_programs/node.py` is imported by
   none of them), so the regression surface is *within* a program: fix the reported
   input, break one that already worked. That is exactly TDAD's signal.
3. **`json_testcases/` and `conftest.py` are protected alongside `python_testcases/`.**
   Editing the expected-output data, or flipping `--correct` to import the gold
   implementation, are the same reward hack by another route.

---

## Ground rules

- Nothing is ever pushed to a real remote. The "commit" action sits behind a human
  checkpoint; `--yes` auto-approves only so the batch eval can run unattended.
- No credential reaches a cassette. Only messages and response bodies are recorded,
  and a redaction pass runs over both before writing.
- `langgraph>=1.0.10` is pinned: CVE-2026-28277 is an unsafe msgpack
  checkpoint-deserialization flaw fixed in that release, and this repo is public.
- Live runs may drift even at temperature 0. **The cassette replay is the canonical
  result**; the live run is how it was produced.

See [ATTRIBUTION.md](ATTRIBUTION.md) for what pre-existed this project, and
[CHANGELOG.md](CHANGELOG.md) for the improvement log.
