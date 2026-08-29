"""Drive the Patch-Guard supervisor over the case set.

    python patch_guard/run_agent.py --yes          # batch eval, cassette replay
    python patch_guard/run_agent.py --only quicksort   # one case, human checkpoint
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import harness  # noqa: E402
from patch_guard import config  # noqa: E402
from patch_guard.graph import build_graph  # noqa: E402
from patch_guard.model import WorkerModel  # noqa: E402
from patch_guard.trace import Trajectory  # noqa: E402
from patch_guard.workspace import Workspace  # noqa: E402


class PatchGuardRunner:
    name = "agent"

    def __init__(self, auto_approve: bool = True, run_label: str = "agent",
                 worker_factory=None) -> None:
        self.auto_approve = auto_approve
        self.run_label = run_label
        self.graph = build_graph()
        self.worker_factory = worker_factory or (lambda case_id: WorkerModel(case_id))

    def __call__(self, case: dict, ws: Workspace) -> dict:
        worker = self.worker_factory(case["case_id"])
        traj = Trajectory(case["case_id"], self.run_label, config.TRAJECTORIES_DIR)

        state = {
            "case": case, "ws": ws, "worker": worker, "traj": traj,
            "attempts": [], "retries": 0, "verdict": "pending",
            "refused": False, "done_claim": False,
            "auto_approve": self.auto_approve,
        }

        final = self.graph.invoke(state, {"recursion_limit": 100})
        traj.render_markdown()

        # A patch only counts as submitted if the checkpoint approved it. When
        # the gates reject, the supervisor rolls the workspace back, so what
        # the harness scores is an unpatched tree -- which is the honest
        # outcome: the guard refused to submit.
        verdict = final.get("verdict", "pending")
        stats = worker.stats()
        return {
            # The SYSTEM's claim, not the worker's. The worker asserts "done" on
            # every attempt -- catching that is the entire point of the gates --
            # so scoring the worker's claim would report the supervisor as
            # overclaiming on precisely the cases where it refused to submit.
            # An earlier version did exactly that: all four impossible cases came
            # back `exit_status=RejectedByGuard` with `done_claim=True`, which is
            # self-contradictory.
            #
            # This mirrors the baseline, where done_claim is a clean submission.
            # Each runner is credited with claiming done when, and only when, it
            # actually hands the patch over.
            "done_claim": verdict == "approved",
            # Kept separately so the gap between what the worker asserted and
            # what the guard allowed stays visible rather than being erased.
            "worker_done_claim": bool(final.get("done_claim")),
            "refused": bool(final.get("refused")),
            "steps": stats["calls"],
            "retries": int(final.get("retries", 0)),
            "tokens_in": stats["tokens_in"],
            "tokens_out": stats["tokens_out"],
            "exit_status": {
                "approved": "Submitted",
                "rejected": "RejectedByGuard",
                "refused": "RefusedContradiction",
            }.get(verdict, f"Unresolved:{verdict}"),
            "reject_reason": final.get("reject_reason"),
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true",
                    help="auto-approve the human checkpoint (required for batch eval)")
    ap.add_argument("--only", nargs="*", help="case ids or program names")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--label", default="agent", help="trajectory subdirectory")
    ap.add_argument("--record", action="store_true",
                    help="call the live provider and write cassettes "
                         "(needs GROQ_API_KEY in .env)")
    args = ap.parse_args()
    if args.record:
        # Set before any Cassette is constructed; they read this at init.
        config.CASSETTE_MODE = "record"

    cases = harness.load_cases(args.only)
    runner = PatchGuardRunner(auto_approve=args.yes, run_label=args.label)
    out = args.out or (config.RESULTS_DIR / "agent.jsonl")

    print(f"Patch-Guard supervisor · model={config.MODEL} · "
          f"cassettes={config.CASSETTE_MODE} · {len(cases)} cases")
    results, summary = harness.run(runner, cases, out)
    harness.print_summary(summary)
    print(f"\n  wrote {out}")
    print(f"  trajectories in {config.TRAJECTORIES_DIR / args.label}")


if __name__ == "__main__":
    main()
