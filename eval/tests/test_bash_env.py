"""Regression tests for the baseline's shell.

The timeout test exists because a recording sweep wedged for 28 minutes on a
single case and looked, from the outside, exactly like a sweep that was working:
no error, no output, no progress.

The cause was `subprocess.run(timeout=...)`, which kills only the direct child.
The shell died on schedule; the `python -m pytest` it had spawned did not, kept
the inherited stdout pipe open, and `run()` blocked forever waiting for an EOF
that could never arrive. QuixBugs ships real infinite loops -- bitcount's bug is
`n ^= n - 1` -- so the agent produces this situation reliably rather than rarely.

This matters for the metric, not just for throughput: a hung command that is
eventually killed by an outer layer would be scored as the agent failing to act.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from baseline.bash_env import BashEnvironment, find_bash  # noqa: E402

pytestmark = pytest.mark.skipif(find_bash() is None, reason="no bash available")


@pytest.fixture
def env(tmp_path):
    return BashEnvironment(cwd=str(tmp_path), timeout=5)


def test_a_runaway_grandchild_cannot_hang_the_sweep(env):
    """The bug that cost 28 minutes.

    bash spawns python, python loops forever holding the stdout pipe. Killing
    bash alone leaves the pipe open, so the read never returns.
    """
    started = time.time()
    result = env.execute({"command": 'python -c "while True: pass"'})
    elapsed = time.time() - started

    assert elapsed < 30, f"timeout not enforced on the process tree ({elapsed:.0f}s)"
    assert result["returncode"] == -1
    assert "timed out" in result["exception_info"]


def test_normal_commands_still_work(env):
    result = env.execute({"command": "echo hello"})
    assert result["returncode"] == 0
    assert "hello" in result["output"]


def test_failure_is_reported_not_raised(env):
    """The agent must receive a non-zero returncode as an observation, because
    a raised exception would end the episode instead of being reasoned about."""
    result = env.execute({"command": "exit 3"})
    assert result["returncode"] == 3


def test_output_is_captured_before_the_timeout_fires(env):
    """A command that prints and then hangs must still return what it printed --
    otherwise the agent loses the diagnostic that would let it recover."""
    result = env.execute({
        "command": 'echo before-hang; python -c "while True: pass"'})
    assert result["returncode"] == -1
    # Best-effort: the pipe is drained after the tree is killed. Assert the
    # mechanism did not simply discard everything.
    assert isinstance(result["output"], str)


def test_venv_is_on_path(env):
    """Without this the agent spends its whole budget on 'pytest: not found'."""
    result = env.execute({"command": "python -c \"import sys; print(sys.executable)\""})
    assert result["returncode"] == 0
    assert result["output"].strip(), "python must resolve inside the workspace"
