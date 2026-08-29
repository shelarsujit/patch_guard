"""pytest plugin that dumps per-node outcomes as JSON.

Loaded into the workspace pytest subprocess with ``-p patch_guard._report_plugin``
and pointed at an output file via ``PATCHGUARD_REPORT``.

Why a plugin rather than ``--junitxml``: the metric is defined over pytest node
ids (``python_testcases/test_x.py::test_x[case3]``), and junit's
``classname``/``name`` split forces a lossy reconstruction of exactly those ids.
Getting a node id wrong silently mislabels a regression, so the ids are recorded
verbatim at the source.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict


class _Collector:
    def __init__(self, path: str) -> None:
        self.path = path
        # nodeid -> phase -> outcome. A node "passed" only if no phase failed;
        # a setup error and a call failure are different bugs and both matter.
        self.phases: dict[str, dict[str, str]] = defaultdict(dict)
        self.longrepr: dict[str, str] = {}
        self.collect_errors: list[str] = []

    def pytest_runtest_logreport(self, report) -> None:
        self.phases[report.nodeid][report.when] = report.outcome
        if report.outcome == "failed" and report.nodeid not in self.longrepr:
            self.longrepr[report.nodeid] = str(report.longrepr)[:4000]

    def pytest_collectreport(self, report) -> None:
        # A syntax error in a patched module surfaces here, not as a test
        # failure. Without this the suite would look like it merely shrank.
        if report.outcome == "failed":
            self.collect_errors.append(f"{report.nodeid}: {str(report.longrepr)[:2000]}")

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        outcomes: dict[str, str] = {}
        for nodeid, phases in self.phases.items():
            if "failed" in phases.values():
                outcomes[nodeid] = "failed"
            elif phases.get("call") == "skipped" or phases.get("setup") == "skipped":
                outcomes[nodeid] = "skipped"
            else:
                outcomes[nodeid] = "passed"

        payload = {
            "exitstatus": int(exitstatus),
            "outcomes": outcomes,
            "longrepr": self.longrepr,
            "collect_errors": self.collect_errors,
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)


def pytest_configure(config) -> None:
    path = os.environ.get("PATCHGUARD_REPORT")
    if path:
        config.pluginmanager.register(_Collector(path), "patchguard_collector")
