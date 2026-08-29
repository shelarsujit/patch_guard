"""Baseline: unmodified mini-swe-agent, same model, same cases, no supervision.

mini-swe-agent runs exactly as upstream ships it. Cassette record/replay is
achieved by wrapping `litellm.completion` -- the single function its model layer
calls -- so nothing about the agent's own behaviour is altered. That keeps the
baseline credible: the comparison isolates supervision, not prompt quality.

    python baseline/run_baseline.py                 # replay committed cassettes
    python baseline/run_baseline.py --record        # live sweep
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baseline.bash_env import BashEnvironment  # noqa: E402
from baseline.resilient_model import ResilientLitellmModel  # noqa: E402
from eval import harness  # noqa: E402
from patch_guard import config  # noqa: E402
from patch_guard.cassettes import Cassette, key_for  # noqa: E402
from patch_guard.ratelimit import (  # noqa: E402
    BUCKET, QuotaExhausted, estimate_prompt_tokens, is_quota_exhausted,
)
from patch_guard.trace import Trajectory  # noqa: E402
from patch_guard.workspace import Workspace  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "patchguard_baseline.yaml"


class _CassettedCompletion:
    """Drop-in replacement for `litellm.completion` backed by a cassette.

    mini-swe-agent needs the full litellm response object (it reads
    `response.choices[0].message` and calls `response.model_dump()`), so the
    whole serialized response is recorded and rebuilt on replay rather than
    just the assistant text.
    """

    def __init__(self, cassette: Cassette, real_completion) -> None:
        self.cassette = cassette
        self.real = real_completion

    def __call__(self, *args, **kwargs):
        import litellm

        model = kwargs.get("model", "")
        messages = kwargs.get("messages", [])
        # Anything that changes the reply belongs in the key, or a config change
        # silently replays decisions made under the old one. That is not
        # hypothetical: a sweep recorded 83 replies with no tool call, and
        # without the sampling fields here those would have replayed intact
        # through every later fix.
        keyed = messages + [
            {"role": "_tools", "content": str(kwargs.get("tools", ""))},
            {"role": "_sampling", "content": json.dumps({
                "max_tokens": kwargs.get("max_tokens"),
                "extra_body": kwargs.get("extra_body"),
            }, sort_keys=True)},
        ]
        key = key_for(model, keyed, config.TEMPERATURE)

        cached = self.cassette.get(key)
        if cached is None:
            # The baseline's prompts embed live pytest output, including how long
            # the run took, so an exact hash can miss a recording that is present.
            cached = self.cassette.get_normalized(model, keyed, config.TEMPERATURE)
        if cached is None:
            # Tool output is re-executed on replay and can differ in ways
            # normalisation does not cover, so fall back to position in the
            # conversation. Counted separately in the cassette stats.
            cached = self.cassette.get_positional(keyed)
        if cached is not None:
            return litellm.ModelResponse(**cached["response"])

        if self.cassette.mode != "record":
            raise self.cassette.miss(key, messages)

        # Groq reserves max_tokens against the TPM ceiling up front, so pace on
        # prompt + max_tokens rather than on what the reply turns out to cost.
        # See patch_guard/ratelimit.py for why this is proactive, not reactive.
        reserved = estimate_prompt_tokens(messages) + int(kwargs.get("max_tokens") or 0)
        BUCKET.reserve(reserved)
        response = self.real(*args, **kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            actual = (getattr(usage, "prompt_tokens", 0) or 0) + int(kwargs.get("max_tokens") or 0)
            BUCKET.settle(reserved, actual)
        self.cassette.put(key, model, messages, {"response": response.model_dump()})
        return response


def _task_for(case: dict, ws: Workspace) -> str:
    """The task text handed to the baseline agent.

    Deliberately mirrors the supervisor's first patch prompt: same issue text,
    same file path, same file contents. The supervisor's `localize` node gives
    its worker exactly this, so giving the baseline less would mean measuring
    localization ability rather than the effect of the gates.
    """
    rel = f"python_programs/{case['program']}.py"
    return (
        f"{case['issue_text']}\n\n"
        f"The buggy implementation is `{rel}`. Its current contents:\n\n"
        f"```python\n{ws.read(rel).rstrip()}\n```\n"
    )


class BaselineRunner:
    name = "baseline"

    def __init__(self, run_label: str = "baseline") -> None:
        self.run_label = run_label
        self.cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        # Single source of truth for the budget. The README's fairness claim is
        # that the baseline gets strictly more steps than the supervisor gets
        # LLM calls, so the number that is documented must be the number applied.
        self.cfg["agent"]["step_limit"] = config.BASELINE_STEP_LIMIT

    def __call__(self, case: dict, ws: Workspace) -> dict:
        import litellm
        from minisweagent.agents.default import DefaultAgent

        traj = Trajectory(case["case_id"], self.run_label, config.TRAJECTORIES_DIR)
        cassette = Cassette(case["case_id"] + "__baseline")

        # Native tool calling, with upstream's FormatError path used to absorb
        # Groq's occasional malformed-tool-call rejection. See resilient_model.py.
        model_kwargs = {"temperature": config.TEMPERATURE,
                        "max_tokens": config.MAX_OUTPUT_TOKENS,
                        # A sweep with no request timeout stalls silently on a
                        # dead connection -- indistinguishable from working.
                        "timeout": config.REQUEST_TIMEOUT,
                        "num_retries": config.REQUEST_RETRIES}
        # Pin the OpenRouter backend. Unpinned, some backends return the model's
        # reasoning with an empty final channel and no tool call, which scores as
        # the agent failing to act. See config.OPENROUTER_PROVIDERS.
        if routing := config.provider_routing():
            model_kwargs["extra_body"] = routing
        model = ResilientLitellmModel(
            model_name=config.MODEL,
            model_kwargs=model_kwargs,
            cost_tracking="ignore_errors",
        )
        # Bash-backed: upstream LocalEnvironment documents bash but uses
        # shell=True, which is cmd.exe on Windows. See baseline/bash_env.py.
        env = BashEnvironment(cwd=str(ws.root),
                              timeout=self.cfg["environment"]["timeout"])
        agent = DefaultAgent(model, env, **self.cfg["agent"])

        real_completion = litellm.completion
        litellm.completion = _CassettedCompletion(cassette, real_completion)
        try:
            result = agent.run(task=_task_for(case, ws))
        except Exception as exc:
            # mini-swe-agent catches the provider error internally and returns a
            # normal result, so the daily-ceiling check also runs on the exit
            # status below. This branch covers the case where it propagates.
            if is_quota_exhausted(exc):
                raise QuotaExhausted(str(exc)) from exc
            result = {"exit_status": f"{type(exc).__name__}: {exc}", "submission": ""}
        finally:
            litellm.completion = real_completion

        # A run that died on the daily token ceiling measured nothing about the
        # agent. Recording it as a failed case would deflate the baseline's
        # score with a quota artefact.
        if is_quota_exhausted(str(result.get("exit_status", ""))):
            raise QuotaExhausted(str(result.get("exit_status")))

        self._record(traj, agent, result)
        traj.render_markdown()

        exit_status = str(result.get("exit_status", "") or "Unknown")
        return {
            # mini-swe-agent submits only when it believes it is finished, so a
            # clean submission IS its done-claim. Whether that claim holds is
            # what the gates decide.
            "done_claim": exit_status in {"Submitted", "submitted", "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"},
            "refused": "refuse" in str(result.get("submission", "")).lower(),
            "steps": agent.n_calls,
            "retries": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "exit_status": exit_status,
        }

    @staticmethod
    def _record(traj: Trajectory, agent, result: dict) -> None:
        """Flatten mini-swe-agent's linear message history into the same
        trajectory format the supervisor emits, so the two are comparable."""
        for i, msg in enumerate(agent.messages):
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            if role == "assistant":
                actions = (msg.get("extra") or {}).get("actions") or []
                traj.append("assistant", instruction=content,
                            tool_call="\n".join(str(a) for a in actions), retry_index=i)
            elif role in {"user", "tool"}:
                traj.append("observation", tool_response=content, retry_index=i)
            elif role == "exit":
                traj.append("exit", gate_decision=f"agent exited: {content}", retry_index=i)
        traj.append("submit",
                    gate_decision=f"exit_status={result.get('exit_status')} "
                                  f"(unverified -- no gates in the baseline)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="case ids or program names")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--record", action="store_true",
                    help="call the live provider and write cassettes "
                         "(needs GROQ_API_KEY in .env)")
    args = ap.parse_args()
    if args.record:
        # Set before any Cassette is constructed; they read this at init.
        config.CASSETTE_MODE = "record"

    cases = harness.load_cases(args.only)
    runner = BaselineRunner(run_label=args.label)
    out = args.out or (config.RESULTS_DIR / "baseline.jsonl")

    print(f"mini-swe-agent baseline · model={config.MODEL} · "
          f"cassettes={config.CASSETTE_MODE} · {len(cases)} cases")
    results, summary = harness.run(runner, cases, out)
    harness.print_summary(summary)
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
