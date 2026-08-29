"""Per-case sandbox: build it, snapshot it, diff it, roll it back.

A case's workspace is the vendored QuixBugs subset with *every* program at its
gold implementation except the case's own program, which is reverted to the
buggy version. That mirrors a real repo at the moment an issue is filed: one
thing is broken, everything else works, and a patch that damages a shared helper
takes previously-passing tests down with it.
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from patch_guard import config


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Artifacts produced by running the tests, not by the agent. Counting these as
# changes would put a .pytest_cache directory in every recorded patch and make
# "the workspace is clean" impossible to assert after a rollback.
_IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _is_artifact(rel: str) -> bool:
    parts = rel.split("/")
    return (
        any(part in _IGNORED_PARTS for part in parts)
        or rel.endswith(".pyc")
        or parts[-1].startswith("_patchguard")
    )


def _snapshot(root: Path) -> dict[str, str]:
    """Hash every agent-visible file so any modification is detectable later."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if _is_artifact(rel):
            continue
        out[rel] = _sha256(p)
    return out


@dataclass
class Workspace:
    """A disposable checkout the agent is allowed to edit."""

    root: Path
    case_id: str
    baseline: dict[str, str]

    # --- inspection ---------------------------------------------------------

    def changed_files(self) -> dict[str, str]:
        """Map of relative path -> 'modified' | 'added' | 'deleted'."""
        current = _snapshot(self.root)
        changes: dict[str, str] = {}
        for rel, digest in current.items():
            if rel not in self.baseline:
                changes[rel] = "added"
            elif self.baseline[rel] != digest:
                changes[rel] = "modified"
        for rel in self.baseline:
            if rel not in current:
                changes[rel] = "deleted"
        return changes

    def touched(self, prefixes: list[str]) -> list[str]:
        """Changed files living under any of `prefixes`."""
        hits = []
        for rel in sorted(self.changed_files()):
            for prefix in prefixes:
                if rel == prefix or rel.startswith(prefix.rstrip("/") + "/"):
                    hits.append(rel)
                    break
        return hits

    def diff(self) -> str:
        """Unified diff of the workspace against its pristine state."""
        chunks: list[str] = []
        for rel, kind in sorted(self.changed_files().items()):
            pristine = self.pristine_root / rel
            current = self.root / rel
            before = pristine.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if pristine.is_file() else []
            after = current.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if current.is_file() else []
            chunks.extend(
                difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
            )
        return "".join(chunks)

    # --- mutation -----------------------------------------------------------

    @property
    def pristine_root(self) -> Path:
        return self.root.parent / (self.root.name + "__pristine")

    def rollback(self) -> None:
        """Restore the workspace to its pristine state.

        Used when a gate rejects a patch: the next attempt must start from the
        original bug, not from the previous attempt's damage.
        """
        shutil.rmtree(self.root)
        shutil.copytree(self.pristine_root, self.root)

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> None:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


def _clear_dest(dest: Path, attempts: int = 5) -> Path:
    """Return an empty directory at `dest`, or beside it if `dest` is locked.

    Windows refuses to remove a directory while any process holds a handle
    inside it, and the agent's own commands are a reliable source of such
    processes: a QuixBugs infinite loop that outlives its shell keeps its
    working directory locked. One such orphan aborted a recording sweep four
    cases in, with every completed case still unwritten.

    Retrying handles the common transient case (a virus scanner or indexer
    holding a handle for a moment). If the lock persists, building beside the
    locked path is strictly better than losing the run: the workspace is
    disposable and its location is not load-bearing, whereas the sweep is paid
    for in tokens and wall-clock.
    """
    for attempt in range(attempts):
        if not dest.exists():
            return dest
        try:
            shutil.rmtree(dest)
            return dest
        except (PermissionError, OSError):
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))

    for suffix in range(1, 100):
        alt = dest.with_name(f"{dest.name}__{suffix}")
        if not alt.exists():
            return alt
    raise RuntimeError(f"could not obtain a clean workspace at {dest}")


def build(case: dict, dest: Path, source: Path | None = None) -> Workspace:
    """Materialize `case`'s workspace at `dest` and take its pristine snapshot.

    The gold implementations are deliberately NOT copied in. QuixBugs ships
    `correct_python_programs/` alongside the buggy ones, and an agent that can
    see it can solve every case with `cp correct_python_programs/x.py
    python_programs/x.py`. That would score a perfect run while measuring
    nothing. The harness still reads gold from the vendored source when it needs
    it (see `apply_gold_patch`); the agent never sees it.
    """
    source = source or config.QUIXBUGS_DIR
    dest = _clear_dest(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(
        "correct_python_programs", "PROVENANCE.json", "__pycache__"))

    # Start from all-gold, then reintroduce exactly one bug. Gold is read from
    # the vendored source, which stays outside the agent's reach.
    for program in config.PROGRAMS:
        gold = source / "correct_python_programs" / f"{program}.py"
        if gold.is_file():
            shutil.copy2(gold, dest / "python_programs" / f"{program}.py")

    program = case["program"]
    shutil.copy2(source / "python_programs" / f"{program}.py",
                 dest / "python_programs" / f"{program}.py")

    # Impossible variants ship a mutated test file whose assertion contradicts
    # the program's documented spec. A correct agent must refuse, not comply.
    for rel, text in (case.get("overlay_files") or {}).items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    pristine = dest.parent / (dest.name + "__pristine")
    if pristine.exists():
        shutil.rmtree(pristine)
    shutil.copytree(dest, pristine)

    return Workspace(root=dest, case_id=case["case_id"], baseline=_snapshot(dest))


def apply_gold_patch(ws: Workspace, program: str, source: Path | None = None) -> None:
    """Overwrite the buggy program with its gold version.

    Reads gold from the vendored source rather than from the workspace, because
    the workspace deliberately does not contain it -- see `build`.

    This is the harness's self-test: gold must score a perfect net-resolved run.
    If it does not, the metric is wrong and nothing downstream can be believed.
    """
    source = source or config.QUIXBUGS_DIR
    gold = source / "correct_python_programs" / f"{program}.py"
    shutil.copy2(gold, ws.root / "python_programs" / f"{program}.py")
