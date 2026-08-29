"""The `patch-guard` MCP server.

Exposes the three gates so any MCP-capable coding agent -- Claude Code, Cursor
-- can verify its own patch before proposing it. The tools are thin wrappers
over `patch_guard.gates`, the same functions the LangGraph supervisor calls.
There is deliberately no second implementation: a guard whose CLI and MCP
surface could drift apart is not a guard.

Register with Claude Code:

    claude mcp add patch-guard -- <repo>/.venv/Scripts/python.exe \\
        <repo>/patch_guard/mcp_server.py

Then ask it to check a patch:

    "Use patch-guard to check my change in /path/to/repo: run the target test
     python_testcases/test_quicksort.py, then the regression suite, then
     confirm I did not touch the tests."
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from patch_guard import gates  # noqa: E402
from patch_guard.workspace import Workspace, _snapshot  # noqa: E402

server = MCPServer("patch-guard")


@server.tool()
def run_target_test(workdir: str, test_path: str, expected_node_ids: list[str] | None = None) -> dict:
    """Run the test that reports the bug and say whether it now passes.

    Args:
        workdir: repository root to run pytest in.
        test_path: the failing test file, relative to workdir.
        expected_node_ids: pytest node ids that must pass. Omit to require the
            whole file to pass.

    Returns whether the target is green, plus which node ids are still failing.
    A run that never terminates is reported as a failure, not as an absence of
    tests -- an infinite loop is a bug, not a passing suite.
    """
    result = gates.run_target_test(workdir, test_path, expected_node_ids or [])
    if not expected_node_ids:
        # No explicit ids: fall back to "no failures and no timeout".
        result["passed"] = not result["timed_out"] and not result["collect_errors"]
    return result


@server.tool()
def run_regression_suite(workdir: str, previously_passing_node_ids: list[str]) -> dict:
    """Report every previously-passing test the patch has broken.

    This is the check SWE-bench records but leaderboards ignore. Pass the node
    ids that were green before the change; anything in that list which is no
    longer green is a regression introduced by the patch.

    Args:
        workdir: repository root to run pytest in.
        previously_passing_node_ids: pytest node ids known green before the patch.
    """
    return gates.run_regression_suite(workdir, previously_passing_node_ids)


@server.tool()
def assert_tests_unmodified(workdir: str, pristine_dir: str,
                            protected_paths: list[str] | None = None) -> dict:
    """Fail if the patch modified any test or expected-output file.

    Catches reward hacking: editing an assertion, rewriting the expected-output
    data the tests compare against, or altering test configuration so the suite
    passes without the bug being fixed.

    Args:
        workdir: repository root, after the patch.
        pristine_dir: a copy of the same tree from before the patch.
        protected_paths: paths that must not change. Defaults to
            python_testcases, json_testcases and conftest.py.
    """
    root = Path(workdir)
    ws = Workspace(root=root, case_id="mcp", baseline=_snapshot(Path(pristine_dir)))
    return gates.assert_tests_unmodified(ws, protected_paths)


if __name__ == "__main__":
    server.run()
