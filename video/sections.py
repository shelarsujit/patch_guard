"""Narration and slide content for the submission video.

Every figure here is copied from `results/report.md`, which is generated from
`results/*.jsonl`. If a number moves, regenerate the report and update this file
rather than the other way round.

Narration is written as ordinary spoken English -- contractions, commas where a
speaker would breathe, acronyms and numerals left as themselves. An earlier
version spelled them out phonetically ("M C P", "twenty four points", "read me")
because the Windows SAPI voice mispronounced them. The neural voice reads them
correctly, and the phonetic spellings made it sound like a machine reciting.
"""

from __future__ import annotations

Q = '"'

SECTIONS = [
    dict(
        title="Patch-Guard",
        footer="micro1 Frontier Engineering Challenge 2026",
        lines=[
            ("body", "A verification and regression supervisor for coding agents."),
            ("gap", ""),
            ("dim", "It refuses to let an agent submit a patch unless:"),
            ("good", "1.  the reported failing test now passes"),
            ("good", "2.  no previously-passing test broke"),
            ("good", "3.  the test files were never touched"),
        ],
        say=(
            "Coding agents get graded on one question. Did the failing test pass? "
            "That's not the same question as, did you fix it. "
            "Patch-Guard wraps a cheap coding agent, and refuses to let it submit "
            "unless three things hold at once. The reported test passes. Nothing "
            "that used to pass is broken. And the test files were never touched."
        ),
    ),
    dict(
        title="The bottleneck is human review",
        lines=[
            ("body", "METR had maintainers from scikit-learn, Sphinx and pytest"),
            ("body", "review 296 AI-generated pull requests."),
            ("gap", ""),
            ("bad", "Merge decisions ran ~24 points BELOW SWE-bench resolved scores."),
            ("gap", ""),
            ("dim", "Top rejection reasons: core functionality broken, and the patch"),
            ("dim", "breaking other code. Not style."),
        ],
        say=(
            "Here's why that matters. METR had maintainers from scikit-learn, "
            "Sphinx and pytest review 296 AI-generated pull requests. Merge "
            "decisions came in about 24 points below the benchmark's resolved "
            "scores. The leading reasons were core functionality broken, and the "
            "patch breaking other code. Not style."
        ),
    ),
    dict(
        title="The metric, and a correction",
        lines=[
            ("mono", "net_resolved = target tests pass"),
            ("mono", "           AND zero PASS_TO_PASS regressions"),
            ("mono", "           AND no protected test file modified"),
            ("gap", ""),
            ("dim", "SWE-bench already requires PASS_TO_PASS for a resolved case."),
            ("dim", "An earlier draft of this README claimed otherwise. That was wrong."),
            ("gap", ""),
            ("body", "The real gap is narrower: SWE-bench runs only the test files the"),
            ("body", "PR touched. A regression outside them is invisible."),
            ("good", "This sweeps the whole suite."),
        ],
        say=(
            "The metric is net-resolved. All three conditions at once, or it "
            "doesn't count. One thing to be precise about: SWE-bench's own "
            "resolved metric already requires the pass-to-pass set. An earlier "
            "draft of my README claimed otherwise, and that was wrong. The real "
            "gap is narrower. It runs only the test files the pull request "
            "touched, so a regression outside them is invisible. This sweeps the "
            "whole suite. I'd rather show you a correction, than have you find one."
        ),
    ),
    dict(
        title="Result: same model, only supervision differs",
        lines=[
            ("mono", "                       baseline    Patch-Guard"),
            ("mono", "net-resolved             50%          70%       +20 pts"),
            ("mono", "reward hacking          2 of 4       0 of 4"),
            ("gap", ""),
            ("body", "The +20 was not expected. Gates reject patches, so the prior was"),
            ("body", "that they trade resolution for safety."),
            ("gap", ""),
            ("good", "A rejection carries its reason back to the worker."),
            ("dim", "Two cases the one-shot baseline abandoned came back on a retry."),
        ],
        say=(
            "Same worker model, same temperature, same cases, same starting "
            "information on both sides. The only difference is supervision. "
            "Net-resolved goes from 50 percent, to 70. Reward hacking on "
            "spec-contradicting tests goes from two of four, to zero. The "
            "20-point gain wasn't what I expected. Gates reject patches, so I "
            "predicted they'd trade resolution for safety. They didn't, because a "
            "rejection carries its reason back to the worker. Two cases the "
            "one-shot baseline abandoned came back on a later attempt. The gates "
            "are a repair signal, not just a filter."
        ),
    ),
    dict(
        title="Gate 2 had no evidence, so the eval set was rebuilt",
        lines=[
            ("dim", "Regressions per patch read 0.00 on every sweep -- because on"),
            ("dim", "QuixBugs nothing CAN regress. Independent single files."),
            ("gap", ""),
            ("body", "So: a shared helper behind three callers, with the bug placed so"),
            ("body", "the correct fix is in the caller and the obvious fix is in the"),
            ("body", "helper."),
            ("gap", ""),
            ("mono", "fix the shared helper  ->  target test PASSES"),
            ("bad", "                       ->  4 tests in untouched modules break"),
        ],
        say=(
            "Here's the part I'd push on, if I were reviewing this. Regressions "
            "per patch read zero on every sweep. Not because nothing regressed, "
            "but because on this benchmark nothing could. Its programs are "
            "independent single files, so a one-file patch can't break another "
            "program. Two of my three gates were measured, and the third was "
            "taken on trust. So I built a set that can break. A shared helper "
            "behind three callers, with the bug placed so the correct fix is in "
            "the caller, and the obvious fix is in the helper. Fix it in the "
            "helper, and the target test genuinely passes. A leaderboard calls "
            "that resolved. Four tests, in modules the agent never touched, go red."
        ),
    ),
    dict(
        title="The three gates, over MCP",
        lines=[
            ("dim", "docs/mcp_demo.md -- generated by a real stdio client against a"),
            ("dim", "live server subprocess. Handshake, tool discovery, three calls."),
            ("gap", ""),
            ("mono", "run_target_test          " + Q + "passed" + Q + ": true"),
            ("bad", "run_regression_suite     " + Q + "clean" + Q + ": false,  4 regressions"),
            ("mono", "assert_tests_unmodified  " + Q + "clean" + Q + ": true"),
            ("gap", ""),
            ("body", "An agent trusting only the first tool would submit that patch."),
        ],
        say=(
            "The same three gates are exposed as an MCP server, so Claude Code or "
            "Cursor can check their own work. This transcript is generated by a "
            "real client against a live server. Watch the verdicts disagree. Run "
            "target test says: passed, true. Run regression suite says: four "
            "regressions. An agent that trusted the first tool and stopped would "
            "have submitted that patch. That's the argument for the other two "
            "gates, in one transcript."
        ),
    ),
    dict(
        title="Capability axis: does supervision matter less as models improve?",
        lines=[
            ("mono", "worker           baseline   Patch-Guard    gain"),
            ("mono", "gpt-oss-20b        50%          70%       +20 pts"),
            ("mono", "gpt-oss-120b       70%          80%       +10 pts"),
            ("gap", ""),
            ("bad", "Unsupervised cheating ROSE with capability:  2 of 4 -> 3 of 4"),
            ("good", "Under the gates, at both sizes:              0 of 4"),
        ],
        say=(
            "Then a question this project had been citing, rather than testing. "
            "Prior work reports that gating helps weaker models about twice as "
            "much. So I ran the same cases against a model six times larger. The "
            "gain from supervision halves. 20 points, down to 10. That replicates "
            "the gradient, through a different mechanism. But look at the second "
            "row. Unsupervised, the larger model reward-hacked more, not less. "
            "Three of four, instead of two. Capability bought competence, and cost "
            "integrity. Under the gates, both models cheat zero times. The gates "
            "don't require the worker to be honest."
        ),
    ),
    dict(
        title="What these numbers do not show",
        lines=[
            ("body", "Neither runner ever REFUSED. Correct-refusal is 0 of 4 on both"),
            ("body", "sides. Harm prevented; diagnosis not made."),
            ("gap", ""),
            ("body", "Overclaiming barely appeared: 11 of 14 baseline runs ended by"),
            ("body", "exhausting the step budget, not by declaring false victory."),
            ("gap", ""),
            ("dim", "The supervisor replays 14/14 from cassettes. The baseline 11/14 --"),
            ("dim", "it drives a real shell, and timeouts shift with machine load."),
        ],
        say=(
            "Three things these numbers don't show, stated in the README rather "
            "than left to be found. Neither runner ever refused. Patch-Guard "
            "blocks the cheat, but it never names the contradiction either. Harm "
            "prevented; diagnosis not made. Overclaiming barely appeared: 11 of 14 "
            "baseline runs ended by exhausting the step budget, not by declaring "
            "false victory. And the supervisor replays perfectly from cassettes, "
            "but the baseline only 11 of 14, because it drives a real shell whose "
            "timeouts shift with machine load."
        ),
    ),
    dict(
        title="The finding I did not go looking for",
        lines=[
            ("body", "Building the harness surfaced ELEVEN infrastructure faults that"),
            ("body", "each produced a plausible NUMBER instead of an error:"),
            ("gap", ""),
            ("mono", "gold implementations reachable -> 100% resolved, measuring nothing"),
            ("mono", "undocumented quota ceiling     -> scored as agent failure"),
            ("mono", "one broken import              -> scored as 62 regressions"),
            ("mono", "cassette served a second model -> fabricated a clean finding"),
            ("gap", ""),
            ("good", "Every one of them biased the comparison in this project's favour."),
        ],
        say=(
            "And the finding I didn't go looking for. Building this harness "
            "surfaced eleven infrastructure faults that each produced a plausible "
            "number instead of an error. Gold implementations reachable in the "
            "workspace, which would have scored a perfect run while measuring "
            "nothing. An undocumented quota ceiling, scored as agent failure. One "
            "broken import, scored as 62 regressions. And a cassette that served "
            "one model another model's recordings, which fabricated a clean result "
            "I nearly published. Every one of them, left alone, would have biased "
            "the comparison in this project's favour. At this model tier, most of "
            "what looks like agent failure is harness artifact."
        ),
    ),
    dict(
        title="Reproduce it",
        lines=[
            ("mono", "python run.py sanity      gold 100%  /  no-op 0%"),
            ("mono", "python run.py test        55 adversarial tests"),
            ("mono", "python run.py agent eval  reproduces the numbers exactly"),
            ("gap", ""),
            ("good", "Offline. No API key. $0."),
            ("gap", ""),
            ("dim", "github.com/shelarsujit/patch_guard"),
        ],
        say=(
            "Everything you've seen runs offline, from committed recordings, with "
            "no API key, at zero cost. The harness self-test comes first. Gold "
            "patches must score 100 percent, and a no-op agent must score zero, or "
            "no number downstream is believed. Thank you."
        ),
    ),
]
