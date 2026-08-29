"""Cross-platform task runner -- the Makefile without needing `make`.

Windows has no `make` and PowerShell 5.1 has no `&&`, so every documented
workflow is also reachable here:

    python run.py sanity
    python run.py test
    python run.py record        # live sweep: baseline + agent + report
    python run.py baseline agent eval
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = str(REPO / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))
if not Path(PY).exists():
    PY = sys.executable

TASKS: dict[str, list[list[str]]] = {
    "setup":     [["eval/build_cases.py", "--rebuild"], ["eval/build_impossible.py"]],
    "sanity":    [["eval/harness.py", "--runner", "gold", "--kind", "standard"],
                  ["eval/harness.py", "--runner", "noop", "--kind", "standard"]],
    "test":      [["-m", "pytest", "eval/tests", "-q"]],
    "baseline":  [["baseline/run_baseline.py"]],
    "agent":     [["patch_guard/run_agent.py", "--yes"]],
    "eval":      [["eval/report.py"]],
    "mcp":       [["patch_guard/mcp_server.py"]],
    # Live recording. Safe to re-run: already-recorded calls replay from
    # cassettes, so only genuinely new calls reach the provider. That makes a
    # run interrupted by the free tier's daily cap resumable the next day.
    "record":    [["baseline/run_baseline.py", "--record"],
                  ["patch_guard/run_agent.py", "--yes", "--record"],
                  ["eval/report.py"]],
    "record-baseline": [["baseline/run_baseline.py", "--record"]],
    "record-agent":    [["patch_guard/run_agent.py", "--yes", "--record"]],
}


def main() -> int:
    names = sys.argv[1:] or ["help"]
    if names == ["help"] or "-h" in names or "--help" in names:
        print(__doc__)
        print("tasks: " + ", ".join(TASKS))
        return 0

    for name in names:
        if name not in TASKS:
            print(f"unknown task {name!r}; try: {', '.join(TASKS)}")
            return 2
        for args in TASKS[name]:
            print(f"\n$ python {' '.join(args)}")
            rc = subprocess.run([PY, *args], cwd=REPO).returncode
            if rc != 0:
                print(f"\ntask {name!r} failed (exit {rc})")
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
