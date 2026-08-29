"""Vendor the QuixBugs subset Patch-Guard evaluates on.

QuixBugs is MIT-licensed, so the subset is committed directly into
``eval/data/quixbugs/`` rather than cloned at setup time. That keeps judge
replay fully offline and keeps the repo small -- 10 programs instead of 40.
``LICENSE`` and ``legal_notes.txt`` travel with the code, as MIT requires.

Re-run only to re-vendor from a different upstream commit:

    python eval/vendor_quixbugs.py --src /path/to/QuixBugs-clone

The pinned upstream commit is recorded in ``PROVENANCE.json`` next to the
vendored tree and in ATTRIBUTION.md.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

# The evaluated programs. Chosen for coverage of the two QuixBugs test styles
# (json-driven parametrized cases, and hand-written graph tests sharing node.py)
# so the regression surface includes a genuinely shared helper module.
PROGRAMS = [
    "bitcount",
    "breadth_first_search",
    "depth_first_search",
    "detect_cycle",
    "knapsack",
    "levenshtein",
    "next_permutation",
    "quicksort",
    "shortest_path_length",
    "topological_ordering",
]

# Copied verbatim regardless of program selection: the pytest options plugin,
# the shared linked-list/graph Node type, and the json test-data loader.
SUPPORT_FILES = [
    "conftest.py",
    "LICENSE",
    "legal_notes.txt",
    "python_programs/node.py",
    "correct_python_programs/node.py",
    "python_testcases/node.py",
    "python_testcases/load_testdata.py",
]

DEST = Path(__file__).resolve().parent / "data" / "quixbugs"


def vendor(src: Path, dest: Path = DEST) -> dict:
    if not (src / "python_programs").is_dir():
        raise SystemExit(f"{src} does not look like a QuixBugs checkout")

    commit = subprocess.run(
        ["git", "-C", str(src), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    if dest.exists():
        shutil.rmtree(dest)

    copied: list[str] = []

    def copy(rel: str) -> None:
        s = src / rel
        if not s.is_file():
            raise SystemExit(f"missing upstream file: {rel}")
        d = dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        copied.append(rel)

    for rel in SUPPORT_FILES:
        copy(rel)

    for program in PROGRAMS:
        copy(f"python_programs/{program}.py")
        copy(f"correct_python_programs/{program}.py")
        copy(f"python_testcases/test_{program}.py")
        # Only the json-driven programs have a test-data file; the graph
        # programs build their inputs inline in the test module.
        if (src / f"json_testcases/{program}.json").is_file():
            copy(f"json_testcases/{program}.json")

    provenance = {
        "upstream": "https://github.com/jkoppel/QuixBugs",
        "commit": commit,
        "license": "MIT (see LICENSE; provenance caveats in legal_notes.txt)",
        "programs": PROGRAMS,
        "files": sorted(copied),
    }
    (dest / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path, help="path to a QuixBugs clone")
    args = ap.parse_args()
    p = vendor(args.src)
    print(f"vendored {len(p['programs'])} programs / {len(p['files'])} files")
    print(f"upstream commit {p['commit']}")


if __name__ == "__main__":
    main()
