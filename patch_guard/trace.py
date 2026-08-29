"""Per-case trajectory: JSONL for machines, markdown for judges.

Deliverable (4) asks for agent instructions -> tool responses -> the feedback
that shaped the next step -> retries and human checkpoints. Every node append
records exactly that, so the rendered transcript is the real run rather than a
reconstruction.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class Trajectory:
    def __init__(self, case_id: str, run: str, root: Path) -> None:
        self.case_id = case_id
        self.run = run
        self.dir = root / run
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{case_id}.jsonl"
        self.entries: list[dict] = []
        self.path.write_text("", encoding="utf-8")

    def append(self, node: str, *, instruction: str = "", tool_call: str = "",
               tool_response: str = "", gate_decision: str = "",
               retry_index: int = 0, **extra) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "node": node,
            "retry_index": retry_index,
            "instruction": instruction,
            "tool_call": tool_call,
            "tool_response": tool_response,
            "gate_decision": gate_decision,
            **extra,
        }
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def render_markdown(self) -> Path:
        out = self.dir / f"{self.case_id}.md"
        lines = [f"# Trajectory — `{self.case_id}` ({self.run})", ""]

        for i, e in enumerate(self.entries, 1):
            retry = f" · retry {e['retry_index']}" if e["retry_index"] else ""
            lines.append(f"## {i}. `{e['node']}`{retry}")
            lines.append("")
            if e["instruction"]:
                lines += ["**Instruction to the worker**", "", "```text",
                          _clip(e["instruction"], 2000), "```", ""]
            if e["tool_call"]:
                lines += ["**Tool call**", "", "```", _clip(e["tool_call"], 800), "```", ""]
            if e["tool_response"]:
                lines += ["**Tool response**", "", "```text",
                          _clip(e["tool_response"], 1600), "```", ""]
            if e["gate_decision"]:
                lines += [f"**Gate decision** — {e['gate_decision']}", ""]
            for k, v in e.items():
                if k in {"ts", "node", "retry_index", "instruction",
                         "tool_call", "tool_response", "gate_decision"}:
                    continue
                lines.append(f"- `{k}`: {_clip(str(v), 400)}")
            lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")
        return out


def _clip(text: str, limit: int) -> str:
    text = text.rstrip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [{len(text) - limit} more chars]"
