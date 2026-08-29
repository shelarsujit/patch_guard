"""Generate the coupled case: a bug whose obvious fix breaks its neighbours.

Why this family exists
----------------------
QuixBugs cannot exercise the regression gate. Its programs are independent
single files, so a one-file patch *structurally cannot* break another program's
tests, and `regressions per patch` reads 0.00 no matter how badly a runner
behaves. Two of the three gates were therefore demonstrated on the evaluation
set and the third was only asserted.

Here `textlib.normalize` is imported by three features. The reported bug is in
`slugify`, which fails to strip punctuation. Fixing it inside `slugify` resolves
the issue and breaks nothing. Fixing it by making `normalize` strip punctuation
*also turns the target test green* -- and breaks four tests that were passing.
That is TDAD's pass-to-pass failure mode, and it is exactly what a leaderboard
that reports only the target test would score as resolved.

F2P and P2P are derived by measurement, never hand-written: run the all-gold
tree, then the buggy tree, and freeze the difference into the case JSON.

Usage:  python eval/build_coupled.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from patch_guard import config  # noqa: E402

ISSUE = """The function `slugify` in `python_programs/slugify.py` is failing its test suite.

Documented behaviour:
    Turn a title into a URL slug: lowercased, punctuation removed, spaces
    replaced with single hyphens.

        >>> slugify("Hello, World!")
        'hello-world'

Failing tests:
  - python_testcases/test_slugify.py::test_strips_punctuation
  - python_testcases/test_slugify.py::test_strips_punctuation_mid_name

Note that `python_programs/textlib.py` is shared: `initials` and
`split_sentences` import `normalize` from it as well.
"""


def _outcomes(tree: Path) -> dict[str, str]:
    """Map every test node id in `tree` to its outcome."""
    report = tree / "_outcomes.json"
    env = {"PATCHGUARD_REPORT": str(report)}
    import os

    subprocess.run(
        [sys.executable, "-m", "pytest", "python_testcases",
         "-p", "patch_guard._report_plugin", "-q", "--tb=no",
         "-o", "addopts=", "-p", "no:cacheprovider"],
        cwd=tree, env={**os.environ, **env,
                       "PYTHONPATH": str(config.REPO_ROOT)},
        capture_output=True, text=True, timeout=config.SUITE_TIMEOUT,
    )
    if not report.is_file():
        raise SystemExit("the report plugin wrote nothing -- cannot derive node ids")
    # The plugin writes {outcomes, exitstatus, collect_errors, longrepr}; only
    # the per-node map is wanted here.
    payload = json.loads(report.read_text(encoding="utf-8"))
    report.unlink()
    if payload.get("collect_errors"):
        raise SystemExit(f"collection failed: {payload['collect_errors']}")
    return payload["outcomes"]


def _materialise(dest: Path, buggy: str | None) -> None:
    """Copy the source tree to `dest`, all-gold except optionally one program."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(config.COUPLED_DIR, dest,
                    ignore=shutil.ignore_patterns("correct_python_programs",
                                                  "__pycache__", "README.md"))
    for program in config.COUPLED_PROGRAMS:
        shutil.copy2(config.COUPLED_DIR / "correct_python_programs" / f"{program}.py",
                     dest / "python_programs" / f"{program}.py")
    if buggy:
        shutil.copy2(config.COUPLED_DIR / "python_programs" / f"{buggy}.py",
                     dest / "python_programs" / f"{buggy}.py")


def main() -> None:
    program = "slugify"
    with tempfile.TemporaryDirectory() as tmp:
        gold_tree = Path(tmp) / "gold"
        _materialise(gold_tree, buggy=None)
        gold = _outcomes(gold_tree)

        buggy_tree = Path(tmp) / "buggy"
        _materialise(buggy_tree, buggy=program)
        buggy = _outcomes(buggy_tree)

    failed_on_gold = sorted(n for n, o in gold.items() if o != "passed")
    if failed_on_gold:
        raise SystemExit(
            "the all-gold tree must be green before anything is derived from it; "
            f"these failed: {failed_on_gold}")

    fail_to_pass = sorted(n for n, o in buggy.items()
                          if o != "passed" and gold.get(n) == "passed")
    pass_to_pass = sorted(n for n, o in buggy.items()
                          if o == "passed" and gold.get(n) == "passed")

    if not fail_to_pass:
        raise SystemExit("the bug does not fail any test -- nothing to fix")

    case = {
        "case_id": f"coupled__{program}",
        "kind": "standard",
        "source": "coupled",
        "programs": config.COUPLED_PROGRAMS,
        "program": program,
        "target_test": "python_testcases/test_slugify.py",
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "protected_paths": ["python_testcases", "conftest.py"],
        "editable_paths": ["python_programs"],
        "hangs_when_buggy": False,
        "issue_text": ISSUE,
    }

    out = config.CASES_DIR / f"{case['case_id']}.json"
    out.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {out}")
    print(f"  FAIL_TO_PASS  {len(fail_to_pass)}")
    for n in fail_to_pass:
        print(f"      {n}")
    print(f"  PASS_TO_PASS  {len(pass_to_pass)}  (the regression surface)")


if __name__ == "__main__":
    main()
