"""A bash-backed execution environment for the baseline on Windows.

`minisweagent.environments.local.LocalEnvironment` documents itself as
executing *bash* commands, but it runs them with `shell=True`, which on Windows
selects `cmd.exe`. Upstream's own prompts (and ours) use bash constructs --
heredocs, `&&`, single-quoted strings -- so on Windows the agent's edit commands
fail with syntax errors that have nothing to do with its reasoning.

This subclass changes only *how the shell is spawned*, restoring upstream's
documented behaviour. The agent, its prompts, its model and its step budget are
untouched, so the baseline stays a fair opponent: it is being given a working
shell, not a handicap or an advantage.

It also puts the project virtualenv on PATH so `python` and `pytest` resolve
inside the workspace -- without which the agent burns its whole step budget on
`'pytest' is not recognized as an internal or external command`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from minisweagent.environments.local import LocalEnvironment

REPO_ROOT = Path(__file__).resolve().parent.parent


def find_bash() -> str | None:
    """Locate a POSIX shell. Returns None on systems where one is absent."""
    if os.name != "nt":
        return shutil.which("bash")
    for candidate in (
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        # Skip the WSL shim in System32: it launches a Linux VM with a
        # different filesystem, so the workspace path would not resolve.
        if candidate and "System32" not in candidate and Path(candidate).is_file():
            return candidate
    return None


def _process_group_kwargs() -> dict:
    """Spawn the shell as its own process group so the tree can be killed.

    Without this the timeout path can only reach bash itself, and anything bash
    started outlives it.
    """
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the shell and every process it spawned."""
    if os.name == "nt":
        # taskkill /T walks the child tree; Popen.kill() alone would not.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _venv_bin() -> str:
    d = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    return str(d) if d.is_dir() else ""


class BashEnvironment(LocalEnvironment):
    """LocalEnvironment that always executes through bash."""

    def __init__(self, *, bash_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.bash = bash_path or find_bash()
        if not self.bash:
            raise RuntimeError(
                "No bash found. The baseline agent's prompts use bash syntax; "
                "install Git for Windows, or run the baseline in the devcontainer."
            )

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = action.get("command", "")
        cwd = cwd or self.config.cwd or os.getcwd()

        env = os.environ | self.config.env
        bin_dir = _venv_bin()
        if bin_dir:
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        limit = timeout or self.config.timeout
        try:
            # Popen + explicit tree kill, not subprocess.run(timeout=...).
            #
            # run() kills only the direct child -- bash. The `python -m pytest`
            # grandchild survives, keeps the inherited stdout pipe open, and
            # run() then blocks forever waiting for an EOF that never comes.
            # QuixBugs bugs include real infinite loops (bitcount is `n ^= n-1`),
            # so the agent reliably produces exactly this situation, and a whole
            # recording sweep wedged on it for 28 minutes looking like progress.
            proc = subprocess.Popen(
                [self.bash, "-c", command],
                cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                **_process_group_kwargs(),
            )
            try:
                stdout, _ = proc.communicate(timeout=limit)
                output = {"output": stdout, "returncode": proc.returncode, "exception_info": ""}
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                # The tree is gone, so this drains what was buffered and returns
                # rather than blocking on a pipe an orphan is still holding.
                try:
                    stdout, _ = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    stdout = ""
                output = {
                    "output": stdout or "",
                    "returncode": -1,
                    "exception_info": f"command timed out after {limit}s",
                    "extra": {"exception_type": "TimeoutExpired"},
                }
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent, not raised
            output = {
                "output": "", "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {exc}",
                "extra": {"exception_type": type(exc).__name__, "exception": str(exc)},
            }

        # Preserve upstream's submission protocol verbatim.
        self._check_finished(output)
        return output
