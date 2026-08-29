"""The supervisor graph.

    reproduce -> localize -> patch -> verify -> anticheat -> regression
                                 ^                              |
                                 |                              v
                              reject <----------------------- checkpoint

Order is load-bearing. anticheat runs *before* regression is believed, because
a suite that is green only because the tests were rewritten should never reach
the regression gate at all. Every rejection rolls the workspace back and feeds
its reason into the next patch attempt.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from patch_guard import config, nodes
from patch_guard.nodes import PatchGuardState


def _after_patch(state: PatchGuardState) -> str:
    if state.get("verdict") == "refused":
        return "refused"
    if state.get("patch_source") is None:
        return "reject"
    return "verify"


def _after_verify(state: PatchGuardState) -> str:
    return "anticheat" if state["verify"]["passed"] else "reject"


def _after_anticheat(state: PatchGuardState) -> str:
    return "regression" if state["anticheat"]["clean"] else "reject"


def _after_regression(state: PatchGuardState) -> str:
    return "checkpoint" if state["regression"]["clean"] else "reject"


def _after_reject(state: PatchGuardState) -> str:
    # Budget exhausted -> stop. The supervisor's job is to refuse to submit a
    # bad patch, not to keep paying for attempts until one sneaks through.
    return END if state.get("retries", 0) > config.MAX_RETRIES else "patch"


def build_graph(checkpointer=None):
    g = StateGraph(PatchGuardState)

    g.add_node("reproduce", nodes.reproduce)
    g.add_node("localize", nodes.localize)
    g.add_node("patch", nodes.patch)
    g.add_node("verify", nodes.verify)
    g.add_node("anticheat", nodes.anticheat)
    g.add_node("regression", nodes.regression)
    g.add_node("checkpoint", nodes.checkpoint)
    g.add_node("reject", nodes.reject)

    g.add_edge(START, "reproduce")
    g.add_edge("reproduce", "localize")
    g.add_edge("localize", "patch")

    g.add_conditional_edges("patch", _after_patch,
                            {"verify": "verify", "reject": "reject", "refused": END})
    g.add_conditional_edges("verify", _after_verify,
                            {"anticheat": "anticheat", "reject": "reject"})
    g.add_conditional_edges("anticheat", _after_anticheat,
                            {"regression": "regression", "reject": "reject"})
    g.add_conditional_edges("regression", _after_regression,
                            {"checkpoint": "checkpoint", "reject": "reject"})
    g.add_conditional_edges("reject", _after_reject, {"patch": "patch", END: END})
    g.add_edge("checkpoint", END)

    return g.compile(checkpointer=checkpointer)
