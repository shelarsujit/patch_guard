# Attribution

## Pre-existing work

None of the following was created for this project. All of it predates the
competition.

| Component | Origin | Licence | Used as |
|---|---|---|---|
| **mini-swe-agent** 2.4.6 | Princeton / Stanford ([SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)) | MIT | The baseline agent, run **unmodified**. Chosen because it is purpose-built as a baseline and scores >74% on SWE-bench Verified — a credible opponent, not a strawman. |
| **LangGraph** 1.2.11 | LangChain | MIT | Supervisor graph runtime (`StateGraph`, conditional edges, `interrupt`). |
| **litellm** 1.98.0 | BerriAI | MIT | Provider-agnostic model calls, shared by both runners. |
| **MCP Python SDK** 2.1.1 | Anthropic | MIT | `MCPServer`, stdio transport. |
| **QuixBugs** (commit `4257f44`) | Koppel et al. ([jkoppel/QuixBugs](https://github.com/jkoppel/QuixBugs)) | MIT | The 10 buggy programs, their gold fixes, and their tests. |
| **gpt-oss-20b** | OpenAI, served via Groq | Apache 2.0 weights | The evaluated worker model. |
| **pytest** 9.1.1 | pytest-dev | MIT | Test execution. |

### QuixBugs vendoring

A 10-program subset is committed under `eval/data/quixbugs/` rather than cloned at
setup time, so judge replay is fully offline. MIT permits this provided the licence
travels with the code: upstream `LICENSE` and `legal_notes.txt` are retained
alongside it, and the exact upstream commit is recorded in
`eval/data/quixbugs/PROVENANCE.json`.

**Disclosure on QuixBugs provenance.** Its own `legal_notes.txt` documents a messy
chain of dataset provenance (the programs originate with the now-defunct Quixey;
the author records having been given their blessing, while noting that "nothing
here is legal advice"). Practical risk is low, but it is disclosed rather than
glossed over. HumanEvalFix (`bigcode/humanevalpack`, MIT) is the clean fallback if
this ever matters. BugsInPy was deliberately avoided: it ships no LICENSE file,
which means all rights reserved.

**Contamination.** QuixBugs is a classic dataset and may appear in training data.
This affects absolute solve rates. It does **not** affect the claim this project
actually makes, which is a *relative* comparison — baseline versus supervised, same
model, same cases, same temperature. Contamination that helps one runner helps both.

---

## New work

Everything below was written for this project.

| Component | What it is |
|---|---|
| `patch_guard/gates.py` | The three deterministic gates. Single source of truth for both the graph and the MCP server. |
| `patch_guard/graph.py`, `nodes.py` | The LangGraph supervisor: reproduce → localize → patch → verify → anticheat → regression → checkpoint, with rollback and reason-carrying retries. |
| `patch_guard/workspace.py` | Per-case sandbox construction, content-hash snapshots, diffing, rollback. |
| `patch_guard/cassettes.py`, `model.py` | Hash-keyed LLM decision recorder/replayer with credential redaction. |
| `patch_guard/mcp_server.py` | The `patch-guard` MCP server. |
| `patch_guard/_report_plugin.py` | pytest plugin emitting per-node outcomes as JSON. |
| `patch_guard/trace.py` | Trajectory JSONL + rendered markdown transcripts. |
| `eval/build_cases.py` | Derives and freezes FAIL_TO_PASS / PASS_TO_PASS sets, which QuixBugs does not ship. |
| `eval/build_impossible.py` | Generates the ImpossibleBench-style contradictory-test variants. |
| `eval/metric.py` | The net-resolved metric and its secondary columns. |
| `eval/harness.py` | Case runner, scorer, and the gold / no-op sanity controls. |
| `eval/report.py` | Generates every published number from the raw records. |
| `eval/tests/` | 29 adversarial tests over the gates, cassettes and supervisor. |
| `baseline/run_baseline.py` | Cassette-wraps `litellm.completion` so mini-swe-agent records and replays **without being modified**. |

### Prior art this builds on

The three failure modes and their measurement are not my discovery. This project's
contribution is putting deterministic gates for all three **in the agent's own loop**
and reporting the conjunction as the primary metric:

- ETH Zurich SRI Lab, *Coding Agents Are "Fixing" Correct Code* — premature completion.
- Alonso, Yovine & Braberman, *TDAD*, arXiv:2603.17973 — pass-to-pass regressions.
- Zhong, Raghunathan & Carlini, *ImpossibleBench*, arXiv:2510.20270 — cheating rate,
  and the read-only-tests mitigation the anti-cheat gate implements.
- METR, *Many SWE-bench-Passing PRs Would Not Be Merged into Main* — the real-world
  bottleneck this targets.

### Tooling disclosure

Claude Code was used as a development assistant while building this repository. It
was **not** used as the evaluated worker model — that is `gpt-oss-20b`, for every
measured run in `results/`.

## The submission video

`video/patch-guard.mp4` is generated, not recorded. The generator is not part of
Patch-Guard and is not shipped in this repository (it is in git history at
`c4eb498`), but the third-party software it used is pre-existing work and is
named here for the same reason everything else on this page is:

| Tool | Role | Licence |
|---|---|---|
| [Pillow](https://python-pillow.org/) | draws the slides | MIT-CMU |
| [edge-tts](https://github.com/rany2/edge-tts) | narration, via Microsoft's neural voices | GPL-3.0 (build-time tool only; not linked or redistributed) |
| [FFmpeg](https://ffmpeg.org/) | muxes stills to narration and concatenates | LGPL-2.1+ / GPL-2+ |

The slide text and narration are new work. Every figure on screen is copied from
`results/report.md`, which is generated from `results/*.jsonl`.

