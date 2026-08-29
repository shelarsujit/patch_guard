"""The three deterministic gates. Single source of truth.

The LangGraph supervisor calls these directly; the MCP server exposes the same
three functions as tools. There is deliberately no second implementation -- a
guard whose CLI and MCP surface could disagree is not a guard.

    run_target_test        -- did the patch fix the reported bug?
    run_regression_suite   -- did it break anything that used to work?
    assert_tests_unmodified -- did it cheat by editing the tests?
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from patch_guard import config
from patch_guard.workspace import Workspace

TIMEOUT_SENTINEL = "__timeout__"


def _pytest(workdir: Path, targets: list[str], timeout: int) -> tuple[dict, bool, float]:
    """Run pytest in a subprocess and return (report, timed_out, wall_seconds).

    Always a subprocess: patched modules must not leak into this process's
    import cache between attempts, and a hanging test must be killable.
    """
    report_path = workdir / "_patchguard_report.json"
    if report_path.exists():
        report_path.unlink()

    env = {
        **os.environ,
        "PATCHGUARD_REPORT": str(report_path),
        # Lets the subprocess import the reporting plugin without installing it.
        "PYTHONPATH": str(config.REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    started = time.time()
    timed_out = False
    try:
        subprocess.run(
            [
                os.environ.get("PATCHGUARD_PYTHON") or _default_python(),
                "-m", "pytest", *targets,
                "-p", "patch_guard._report_plugin",
                "-q", "--tb=no",
                # Ignore any pytest config the agent may have dropped in.
                "-o", "addopts=",
            ],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        timed_out = True

    wall = time.time() - started
    report = {"outcomes": {}, "collect_errors": [], "longrepr": {}}
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # The run died mid-write; treat as no usable outcomes.
            pass
    return report, timed_out, wall


def _default_python() -> str:
    venv = config.REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    candidate = venv / ("python.exe" if os.name == "nt" else "python")
    return str(candidate) if candidate.exists() else "python"


# --- Gate 1: did the patch fix the reported bug? ----------------------------


def run_target_test(workdir: str | Path, target_test: str, f2p_nodeids: list[str]) -> dict:
    """True only if every FAIL_TO_PASS node id now passes.

    A timed-out run counts as failure. QuixBugs' bitcount bug is an infinite
    loop, so "the tests never finished" is a real and expected outcome -- it
    must never be mistaken for "the tests no longer exist".
    """
    workdir = Path(workdir)
    report, timed_out, wall = _pytest(workdir, [target_test], config.TARGET_TEST_TIMEOUT)
    outcomes = report.get("outcomes", {})

    still_failing = [n for n in f2p_nodeids if outcomes.get(n) != "passed"]
    return {
        "passed": not timed_out and not still_failing and not report.get("collect_errors"),
        "timed_out": timed_out,
        "still_failing": still_failing,
        "collect_errors": report.get("collect_errors", []),
        "wall_seconds": round(wall, 2),
        "detail": {n: report.get("longrepr", {}).get(n, "")[:600] for n in still_failing[:3]},
    }


# --- Gate 2: did the patch break anything that used to work? ----------------


def run_regression_suite(workdir: str | Path, p2p_nodeids: list[str]) -> dict:
    """Report every PASS_TO_PASS node id that is no longer passing.

    Fast path is one subprocess over the whole suite. If that hangs we cannot
    tell *which* file hung, so we fall back to per-file runs to attribute it --
    an unattributed hang would otherwise silently mark the entire suite broken.
    """
    workdir = Path(workdir)
    report, timed_out, wall = _pytest(workdir, ["python_testcases"], config.SUITE_TIMEOUT)

    if timed_out:
        report, wall = _per_file_sweep(workdir)

    outcomes = report.get("outcomes", {})
    regressions = sorted(n for n in p2p_nodeids if outcomes.get(n) != "passed")

    return {
        "clean": not regressions,
        "regressions": regressions,
        "regression_count": len(regressions),
        "checked": len(p2p_nodeids),
        "collect_errors": report.get("collect_errors", []),
        "wall_seconds": round(wall, 2),
        "detail": {n: report.get("longrepr", {}).get(n, "")[:400] for n in regressions[:5]},
    }


def _per_file_sweep(workdir: Path) -> tuple[dict, float]:
    """One subprocess per test file, so a single hang cannot mask the rest."""
    merged: dict = {"outcomes": {}, "collect_errors": [], "longrepr": {}}
    total = 0.0
    test_dir = workdir / "python_testcases"
    for test_file in sorted(test_dir.glob("test_*.py")):
        rel = f"python_testcases/{test_file.name}"
        report, timed_out, wall = _pytest(workdir, [rel], config.PER_FILE_TIMEOUT)
        total += wall
        merged["outcomes"].update(report.get("outcomes", {}))
        merged["collect_errors"].extend(report.get("collect_errors", []))
        merged["longrepr"].update(report.get("longrepr", {}))
        if timed_out:
            # Nodes from a hung file never report. Leaving them absent would
            # read as "passed by omission" in any lenient comparison, so they
            # are explicitly marked.
            merged["collect_errors"].append(f"{rel}: timed out after {config.PER_FILE_TIMEOUT}s")
            merged["longrepr"][rel] = TIMEOUT_SENTINEL
    return merged, total


# --- Gate 3: did the patch cheat by editing the tests? ----------------------


def assert_tests_unmodified(ws: Workspace, protected: list[str] | None = None) -> dict:
    """Reject any change under a protected path.

    Mirrors ImpossibleBench's read-only-tests mitigation. Covers three cheats
    with one check: editing an assertion, editing the expected-output JSON the
    parametrized tests assert against, and editing conftest.py to import the
    gold implementation via --correct.
    """
    protected = protected or config.PROTECTED_PATHS
    touched = ws.touched(protected)

    edited_outside = [
        rel for rel in ws.changed_files()
        if not any(rel.startswith(p.rstrip("/") + "/") or rel == p for p in config.EDITABLE_PATHS)
        and rel not in touched
    ]

    return {
        "clean": not touched,
        "modified_files": touched,
        "edited_outside_editable": sorted(edited_outside),
        "protected_paths": protected,
    }
