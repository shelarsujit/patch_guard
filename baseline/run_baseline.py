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
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baseline.bash_env import BashEnvironment  # noqa: E402
from eval import harness  # noqa: E402
from patch_guard import config  # noqa: E402
from patch_guard.cassettes import Cassette, key_for  # noqa: E402
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
        # Tool definitions are part of the request, so they belong in the key --
        # otherwise a changed tool schema would silently replay stale decisions.
        keyed = messages + [{"role": "_tools", "content": str(kwargs.get("tools", ""))}]
        key = key_for(model, keyed, config.TEMPERATURE)

        cached = self.cassette.get(key)
        if cached is not None:
            return litellm.ModelResponse(**cached["response"])

        if self.cassette.mode != "record":
            raise self.cassette.miss(key, messages)

        import time
        time.sleep(1.0)  # light pacing; litellm retries handle the 8k TPM ceiling
        response = self.real(*args, **kwargs)
        self.cassette.put(key, model, messages, {"response": response.model_dump()})
        return response


class BaselineRunner:
    name = "baseline"

    def __init__(self, run_label: str = "baseline") -> None:
        self.run_label = run_label
        self.cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def __call__(self, case: dict, ws: Workspace) -> dict:
        import litellm
        from minisweagent.agents.default import DefaultAgent
        from minisweagent.models.litellm_model import LitellmModel

        traj = Trajectory(case["case_id"], self.run_label, config.TRAJECTORIES_DIR)
        cassette = Cassette(case["case_id"] + "__baseline")

        model = LitellmModel(
            model_name=config.MODEL,
            model_kwargs={"temperature": config.TEMPERATURE,
                          "max_tokens": config.MAX_OUTPUT_TOKENS},
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
            result = agent.run(task=case["issue_text"])
        except Exception as exc:
            result = {"exit_status": f"{type(exc).__name__}: {exc}", "submission": ""}
        finally:
            litellm.completion = real_completion

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
