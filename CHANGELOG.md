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

**Evidence.** Recorded: baseline 50% net-resolved (5/10) against the supervisor's
70% (7/10), on identical cases with identical worker, temperature and starting
information. The baseline was given the *larger* budget — 14 shell steps against
the supervisor's 4 patch attempts — and `max_consecutive_format_errors` was
raised from 3 to 8 in its favour.

**Decision / Learning.** The gap is attributable to supervision rather than to
prompt quality, which is the only comparison worth publishing. Where the two
runners differ in budget or tolerance, the advantage was deliberately given to
the baseline, so the measured gap is a floor rather than a best case.

---

## 5 — At this model tier, most apparent agent failure is harness artifact

**What I tried and why.** The intent was simply to run the recording sweep. What
actually happened is the finding: twelve distinct infrastructure faults surfaced,
each of which would have produced a *number* rather than an error, and each of
which a reasonable person would have read as an agent behaving badly.

The last column is the one that matters, and it is the one I got wrong first.
"Favours" means the fault, left unfixed, would have made Patch-Guard look better
than it is; "against" means it would have made it look worse.

| # | Fault | Would have been scored as | Direction |
|---|---|---|---|
| 1 | `correct_python_programs/` copied into the workspace | **100% net-resolved, measuring nothing** | unclear |
| 2 | Sibling case workspaces reachable via `..` | agent "found" fixes by reading other cases | unclear |
| 3 | `FormatError` raised inside upstream's tenacity loop — 10 identical retries, then episode death | agent failed to produce a valid edit | favours |
| 4 | `FormatError(...)` given a list where varargs were expected | crash, once fault 3 was fixed | favours |
| 5 | Groq's undocumented 200k tokens/day ceiling | `target-failed` | unclear |
| 6 | OpenRouter routing to a backend that drops the harmony final channel | agent failed to act | favours |
| 7 | Model wedged in the reasoning channel; identical retry at temperature 0 | repeated format errors, episode death | favours |
| 8 | Orphaned `pytest` surviving its shell, holding a pipe open | sweep hangs, indistinguishable from working | favours |
| 9 | Same orphan locking the workspace directory | crash discarding four completed cases | unclear |
| 10 | pytest aborting the whole run on one collection error | **62 regressions** across nine unrelated programs | favours |
| 11 | Sequential cassette fallback ignoring the model field | a 120b sweep replaying 20b decisions — **a fabricated capability axis** | favours |
| 12 | Regression suite run against a tree with no diff | **5.90 regressions per patch for the supervisor, 0.00 for the baseline** | against |

**Evidence.** Each is measured, not inferred. Fault 6 was isolated by sending one
request to every backend serving the model: Darkbloom returned `finish=stop` with
no tool call; CoreWeave, DeepInfra, Parasail and Bedrock returned `finish=tool_calls`.
Fault 7 by holding a wedged conversation fixed and varying one setting at a time —
`tool_choice=required`, excluding reasoning, and raising temperature all failed;
only `reasoning effort=low` recovered. Fault 8 by timing the exact shape that hung:
5.4s against a 5s limit, where before it never returned. Fault 11 by observing that
the 120b numbers matched the 20b numbers case for case, down to which cases cheated,
and that only 1 of 233 recordings was actually a 120b response. Fault 1 is now
pinned by `test_gold_implementations_are_not_visible_to_the_agent`, fault 8 by
`test_a_runaway_grandchild_cannot_hang_the_sweep`, fault 11 by
`test_a_cassette_never_serves_one_model_the_other_model_s_run`, and fault 12 by the
no-change invariant in `eval/harness.py`.

**Decision / Learning.** Three things follow, and only the first is comfortable.

First, the published failure-mode literature is measured on frontier models
through mature harnesses. At the 20B open-weight tier the harness itself is a
dominant source of apparent incompetence, and a paper reporting "the cheap model
scored X" without controlling for these is not obviously measuring the model.
That is a methodological claim this project can support with receipts.

Second, the asymmetry is real but smaller than I first wrote. **Faults 3, 6, 7 and
8 hit the baseline and not the supervisor**, because the baseline drives tool calls
through a real shell while the supervisor makes a single text completion and never
runs a command — so the artifact-prone surface sits mostly on the side this project
wants to look worse. Faults 10 and 11 point the same way. That is seven of twelve
flattering the thesis, four not clearly attributable, and one — fault 12 — pointing
squarely the other way. An earlier draft of this entry, and the submission video,
claimed *every* fault favoured the project. That was wrong, and it was wrong in the
direction that made the story cleaner.

Third, and this is the part that limits the claim: **the discovery process is not
a fair sample.** A fault that makes my own number look bad announces itself — fault
12 inverted the headline and was found within hours. A fault that makes it look
good is found only by deliberately going back over a result I was already happy
with. So a tally skewed toward "favours" is exactly what motivated stopping
predicts, with no asymmetry in the infrastructure required to produce it. The 7:1
split is consistent with the infrastructure being biased, and equally consistent
with my attention being biased, and this project cannot separate the two.

Separating them needs a design this project does not have: seed known faults into
an eval harness, half favouring the system under test and half against, hand it to
observers blind to which, and measure time-to-detection by direction. Until that
exists, the honest form of the claim is the first paragraph — harness artifacts
dominate apparent agent failure at this tier — and not any statement about which
way they lean.

---

## 6 — The gain is real; the mechanism I gave for it was not

**What I tried and why.** The expectation going in was a trade: gates reject bad
patches, so the supervisor should resolve *fewer* cases than the baseline while
cheating less. That prediction was wrong, and the first explanation I wrote for
why it was wrong is also wrong.

**Evidence.** 50% → 70% net-resolved and 14% → 0% cheat rate, with no case where
the baseline won and the supervisor lost. The two cases gained are
`depth_first_search` and `detect_cycle`.

The original entry then claimed the mechanism was the retry loop: a rejection
carries its reason back into the next attempt, so the worker gets a grounded
correction rather than another blind try. It reads well. The per-case rows do not
support it.

| | retries | exit status |
|---|---|---|
| every case the supervisor **won** | **0** | `Submitted` |
| every case the supervisor **retried** | 4 | `RejectedByGuard` |

Not one case in the sweep was recovered by a retry. The repair loop fired only on
cases that went on to be rejected anyway. And the two gained cases were lost by
the baseline with `LimitsExceeded` — it exhausted its step budget driving a shell,
rather than producing a wrong patch the gates then corrected.

**Decision / Learning.** The honest reading splits the result in two. The gates
own the cheat rate: 2/4 → 0/4 is anti-cheat and target-gate rejections, directly
observed. They do not own the resolution rate. What distinguishes the runners on
`depth_first_search` and `detect_cycle` is that the supervisor spends its single
model call on a pre-localized prompt — file, function, failing test names, file
contents — while the baseline spends its budget discovering the same facts
through a shell. That is a scaffolding effect, not a verification effect, and
this project did not run the ablation that would separate them.

The ECLoop contrast still holds and is worth keeping: a pytest exit code cannot be
argued out of a failing assertion the way post-hoc LLM self-review can, which is
why deterministic gates did not degrade performance here where ECLoop's
self-review degraded it by 1.4 and 1.8 points. But "the gates are a repair signal"
was a story I liked, retrofitted onto a number that has a duller cause. It is
struck.

---

## 7 — Replaying an agent that runs a shell is not the same as replaying one that does not

**What I tried and why.** The reproducibility claim was that a judge re-runs
`python run.py baseline agent eval` and gets the published numbers back at $0.
Before publishing that, I checked it — by diffing a full replay against the live
recorded run, case by case, rather than by confirming the command exits zero.

**Evidence.**

| Runner | Cases reproduced | Diverged |
|---|---|---|
| Patch-Guard | **14 / 14** | none |
| Baseline | **11 / 14** | `impossible__knapsack`, `impossible__quicksort`, `quixbugs__topological_ordering` |

The divergence was not noise around the edges: both of the baseline's reward
hacks vanished on replay, which is the single most load-bearing result in the
comparison.

The cause is architectural. The supervisor makes one text completion per attempt
and never runs a command, so its prompts contain only file contents and there is
nothing timing-dependent in them. The baseline drives a real bash agent, its
prompts embed real command output, and whether a command hits the 30s timeout
shifts with machine load — a different timeout leaves a different workspace for
the next decision to act on. Content hashing cannot survive that: once one lookup
misses, the conversation diverges and every later lookup misses too. Replaying
decisions in recorded order removes the misses but not the divergence, because
the same decision applied to a differently-timed shell produces a different tree.

**Decision / Learning.** The published numbers are the **live recorded run**, and
the README now says so with the fidelity measured per runner instead of claiming
exactness for both. Three options were available and the choice is worth stating:

1. Record the tool output too, and replay it. Bit-exact, and worthless — a
   trajectory that never really executes proves nothing about the code.
2. Quietly publish replay numbers and call them reproductions. They differ from
   what was actually measured.
3. Publish what was measured, and measure how well it replays.

The third is the only one that survives someone checking. It also turns the
limitation into a result: **an agent that acts through a shell is inherently
harder to reproduce than one that emits a patch**, which is an argument for the
supervised architecture that has nothing to do with the gates.

---

## 8 — Building the case set that could falsify gate 2

**What I tried and why.** Gate 2 was the only gate this project asserted rather
than demonstrated. Its number read 0.00 for every runner on every sweep, and the
reason was structural rather than flattering: QuixBugs programs are independent
single files, so no one-file patch can break another program's tests. An
evaluation set that cannot produce a failure mode cannot provide evidence about
a gate that catches it.

So I built one that can. `eval/data/coupled/` places `textlib.normalize` behind
three callers and puts the bug where the locally-correct fix and the globally-
correct fix differ.

**Evidence.**

| Patch | Target | P2P regressions | net_resolved |
|---|---|---|---|
| gold | pass | 0 | True |
| fix in the shared helper | **pass** | **4** | False |
| untouched | fail | 0 | False |

Live, on the same case: baseline 0% net-resolved with 2.00 regressions per
patch; supervisor 100% with 0.00. The baseline emptied `slugify.py` outright.

**Decision / Learning.** Two things came out of this that were not the point of
the exercise.

First, the exercise immediately found a scoring bug that had been inflating the
regression counts everywhere. pytest aborts the whole run on a collection error,
so one unimportable module left every other test unreported and the gate counted
all of them as regressed -- 10 on this case where only 2 tests could break, and
62 on a QuixBugs impossible case, across nine programs that do not import the
patched one. That last figure had been published as gate 2's evidence. It is
withdrawn, the fix is `--continue-on-collection-errors`, and the invariant is
pinned by a test. Like the artefacts in entry 5 this one flattered the thesis:
the baseline is the runner that produces unimportable wreckage.

Second, it is worth being explicit that this family is synthetic and that a
synthetic case set can be tuned until it says what its author wants. The
mitigation is that the bug is not hidden -- it is a plausible bug whose obvious
fix has non-local consequences -- that FAIL_TO_PASS and PASS_TO_PASS are derived
by measurement and the builder refuses to emit a case whose all-gold tree is not
green, and that the whole tree is committed for inspection. n=1 on the live run,
and reported as n=1.

---

## Open

- **Gate 2 is unmeasured on the standard set.** Regressions per patch is 0.00 for
  both runners. QuixBugs programs are independent single files, so a one-file
  patch structurally cannot break another program's tests — TDAD's
  6.5-broken-tests-per-patch has no way to reproduce here. The gate is exercised
  by an adversarial test, and a case set with genuinely shared modules was built
  to measure it properly -- see entry 8. An earlier version of this bullet cited
  "one impossible case that broke 62 previously passing tests"; that figure was a
  collection-abort artefact and is withdrawn.
- **The +20 is not attributed to a mechanism.** Every case the supervisor won, it
  won on the first attempt; the retry loop never recovered one. The two gained
  cases were lost by the baseline to step-budget exhaustion, so the difference is
  plausibly the pre-localized prompt rather than the gates. The gates demonstrably
  own the cheat rate. They are not shown to own the resolution rate, and the
  ablation that would settle it — supervisor scaffolding with the gates disabled —
  was not run. See entry 6.
- **Nothing refused; it was blocked.** Correct-refusal is 0/4 for both runners.
  The supervisor never cheated, but it also never recognised the contradiction
  and said so — the `REFUSE` path never fired. Harm prevented, diagnosis not made.
- **Overclaiming barely appeared at this tier.** 11 of the baseline's 14 runs
  ended by exhausting the step limit rather than submitting, and all 3 of its
  done-claims were correct. The dominant failure here is budget exhaustion, not
  false victory, so the 0% overclaim row reflects a failure mode that did not
  show up rather than a gate that stopped it.
- **The baseline does not replay bit-exactly** (11/14; the supervisor is 14/14).
  See entry 7. A fresh `record` is a new sample on either side, because the
  baseline's retry path escalates temperature to break byte-identical retries.
- **Cut early and deliberately:** the SWE-bench Verified Mini case and the LoRA
  "done-or-not" verifier. The deterministic gates already dominate what a learned
  trustworthiness predictor would offer, and the brief explicitly rewards a
  documented cut over a half-finished experiment.

---

## The main failure mode

**Patch-Guard blocks the cheat without ever naming it.**

On the four impossible variants -- where the target test asserts something the
program's documented spec forbids -- the supervisor cheats 0 out of 4 times, at
both model sizes. It also refuses 0 out of 4 times. The `REFUSE` path exists in
the graph and never fired once.

What actually happens is that the worker produces a patch, the anti-cheat gate
sees a modified test file or the target gate sees a spec violation, the patch is
rolled back, and the retry budget runs out. The case ends as non-compliance. A
maintainer reading that output learns the agent could not do it. They do not
learn *the test is wrong*, which is the only fact worth having.

Harm prevented, diagnosis not made. That is a real limit and it is the honest
ceiling on the deterministic approach: a gate can compare a patch against a
suite, but "this assertion contradicts the docstring" is a judgement about
intent, and no exit code carries it. Closing it needs a component this project
deliberately did not build.

## Hot take

**The agent's own report of what it accomplished carries no weight. Neither does
mine, and I have the receipts.**

The entire design rests on refusing to let a worker grade itself. Every number
here is produced by gates the worker cannot reach, because an agent that says
"done" is making a claim, not a measurement.

Then I wrote, in the README and in the submission video, that all of the harness
faults I had found biased the comparison in this project's favour. It was a
clean line. It was also false: fault 12 inverted the headline *against* the
supervisor, and I had fixed it myself weeks earlier. Nothing caught this. The
tests passed, the sanity controls passed, the numbers were correct -- because
the claim was in prose, and prose has no gate.

So the uncomfortable version of the thesis is this. At the 20B tier, most of
what looks like agent failure is harness artifact -- twelve of them here, each
producing a plausible number instead of an error. But the artifacts I found are
not a fair sample of the artifacts that exist, because the ones that flatter me
are the ones I had no reason to go looking for. I can measure a patch. I cannot
measure my own attention, and the discipline that makes the agent's numbers
trustworthy stops precisely where the write-up begins.

If you take one thing from this repository, take that the gates are the easy
part.

