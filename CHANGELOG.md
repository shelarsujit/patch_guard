# Improvement Changelog

Logged live as the work happened, not reconstructed afterwards. Every number
comes from `results/*.jsonl` via `eval/report.py`.

Format: **Stage · What I tried and why · Evidence · Decision / Learning**

---

## 0 — Build the eval harness before building the agent

**What I tried and why.** Wrote the metric, the workspace builder and the three
gates first, with no agent attached. A metric written after the agent tends to
flatter the agent.

QuixBugs ships no FAIL_TO_PASS / PASS_TO_PASS sets, so I derived them: run the
all-gold tree to establish what works, reintroduce one bug, and freeze the two
node-id sets into `eval/cases/`. Freezing matters — if the sets were recomputed at
eval time, a patch that deleted a test would also delete the evidence that it used
to pass.

**Evidence.**

| Control | Expected | Measured |
|---|---|---|
| Gold patch | 100% net-resolved | **100%** (10/10) |
| No-op agent claiming success | 0% net-resolved | **0%** (0/10), overclaim rate **100%** |

All-gold tree: 68 passed, 2 skipped, 0 failed. Each buggy program fails **only its
own** tests — zero off-target failures across all 10 — so PASS_TO_PASS starts clean.

**Decision / Learning.** The two controls are wired into `make sanity` and exit
non-zero on violation. Nothing downstream is believed unless both hold. Three
measurements changed the design before a single LLM call was made:

1. **`bitcount` hangs.** Its bug (`n ^= n - 1` instead of `n &= n - 1`) is an
   infinite loop. A single suite-wide pytest run is therefore unusable. Every
   invocation is now wall-clocked, and a hang is recorded as a *failure* — never as
   a test that quietly stopped existing.
2. **The cross-program regression surface is empty.** I assumed
   `python_programs/node.py` was a shared helper worth breaking; measurement showed
   **no program imports it** (the tests use the protected `python_testcases/node.py`).
   So the honest regression signal is *within* a program: fix the reported input,
   break one that already worked. That is precisely TDAD's pass-to-pass finding, and
   arguably a purer form of it.
3. **Two more cheat vectors existed than I had guarded.** `json_testcases/*.json`
   holds the expected values the parametrized tests assert against, and `conftest.py`
   sets `pytest.use_correct`, which would import the gold implementation outright.
   Both joined `python_testcases/` as protected paths.

---

## 1 — Gates written adversarially, not hopefully

**What I tried and why.** Rather than wait to see whether a stochastic model
happened to misbehave, I wrote 29 tests that misbehave on purpose: patches that
regress, patches that edit assertions, patches that delete tests, patches that
rewrite expected-output JSON, replies with no code in them.

**Evidence.** 29/29 passing. Two findings worth recording:

- **The test-editing cheat is caught by two independent gates, for different
  reasons.** Deleting test bodies removes the FAIL_TO_PASS node ids, so it dies at
  `verify` ("those tests did not pass"). Merely *weakening* an assertion keeps every
  node id green and sails through `verify` — only diffing protected paths catches
  it. Neither gate alone is sufficient.
- **A real bug surfaced.** The pytest subprocess was writing `.pytest_cache/` into
  the workspace, which the content-hash snapshot counted as agent-added files. That
  would have put cache directories in every recorded patch and made
  "the workspace is clean after rollback" impossible to assert. Fixed at both layers
  (`-p no:cacheprovider` plus an artifact filter in the snapshot).

**Decision / Learning.** Adversarial tests earned their place immediately — the
`.pytest_cache` bug was invisible to every happy-path run and would have quietly
corrupted the headline artifact. Kept, and extended to the supervisor.

---

## 2 — Gate ordering: anti-cheat before regression

**What I tried and why.** The obvious ordering is verify → regression → anti-cheat,
cheapest signal first. That ordering is wrong. A suite that is green *only because
the tests were rewritten* would reach the regression gate and be judged against
tests the agent authored.

**Evidence.** `test_weakening_assertions_is_caught_by_anticheat` — with assertions
neutered, the target test genuinely passes and the regression suite is genuinely
clean. Every signal downstream of `verify` is compromised.

**Decision / Learning.** `anticheat` runs before `regression` is believed, and a
protected-path touch is an immediate rollback. **Integrity checks must precede
correctness checks, because correctness checks read from the thing integrity
protects.**

---

## 3 — Rejection carries its reason back to the worker

**What I tried and why.** A rejected patch that is retried with the same prompt
produces the same patch, burning the whole retry budget on one idea. Each rejection
now appends `{reason, evidence}` to an attempt log that is rendered into the next
prompt, and rolls the workspace back so the next attempt starts from the original
bug rather than the previous attempt's damage.

**Evidence.** `test_regressing_patch_is_rejected_and_retried` asserts the retry
prompt contains both `REJECTED` and the phrase `previously passing` — the worker is
told *why*, not merely *that*. `test_persistent_regression_is_never_submitted`
asserts that an agent which cannot stop regressing ends at `RejectedByGuard` with a
workspace containing zero changes.

**Decision / Learning.** Rollback is not housekeeping, it is correctness: without it,
attempt 2 is scored against attempt 1's wreckage.

---

## 4 — Baseline runs upstream mini-swe-agent unmodified

**What I tried and why.** A baseline I had edited would be a strawman. Instead,
cassette record/replay wraps `litellm.completion` — the single function
mini-swe-agent's model layer calls — so the agent itself is untouched. It gets the
same model, temperature, cases and step budget, and is told in the same words that
tests are off limits.

**Evidence.** Pending — requires a `GROQ_API_KEY` to record. See "Open" below.

**Decision / Learning.** Any measured gap is then attributable to supervision rather
than to prompt quality, which is the only comparison worth publishing.

---

## Open

- **Recording run not yet performed.** Everything is implemented, tested and wired;
  the baseline-vs-agent numbers require one live recording sweep against Groq's free
  tier. `make sanity`, `make test` and the MCP server all run today with no key.
- **Cut early and deliberately:** the SWE-bench Verified Mini case and the LoRA
  "done-or-not" verifier. The deterministic gates already dominate what a learned
  trustworthiness predictor would offer, and the brief explicitly rewards a
  documented cut over a half-finished experiment.
