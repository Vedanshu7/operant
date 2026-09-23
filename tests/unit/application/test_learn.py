"""
``graph learn`` reads arrivals from every version a capability ran on.
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict, List, Optional

import operant.application.drift as apdrift
import operant.domain.models.graph as graph
import tests.support.capabilities as capab

# #############################################################################
# _Graphs
# #############################################################################


class _Graphs:

    def __init__(self, *versions: graph.AppGraph) -> None:
        self.stored = {g.graph_version: g for g in versions}

    def get(self, vendor: str, version: Optional[int] = None) -> graph.AppGraph:
        return self.stored[version or max(self.stored)]

    def versions(self, vendor: str) -> List[int]:
        return sorted(self.stored)

    def save_new_version(self, document: graph.AppGraph) -> graph.AppGraph:
        return document


def _graph(version: int, pattern: str = "page") -> graph.AppGraph:
    return graph.AppGraph(
        vendor_id="v",
        graph_version=version,
        nodes=[capab.node("page", pattern)],
    )


def _log(root: pathlib.Path, *events: Dict[str, object]) -> None:
    run = root / "run"
    run.mkdir(exist_ok=True)
    with (run / "run-log.jsonl").open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _arrival(version: int, minute: int) -> Dict[str, object]:
    return {
        "type": "node_arrived",
        "at": f"2026-11-01T00:{minute:02d}:00+00:00",
        "node": "page",
        "vendor_id": "v",
        "graph_version": version,
        "fingerprint": ["a", "b"],
        "url_path": "/page",
    }


def test_visits_on_a_pinned_version_still_count(tmp_path: pathlib.Path) -> None:
    _log(tmp_path, _arrival(3, 1), _arrival(3, 2), _arrival(3, 3))
    learned = apdrift.learn("v", tmp_path, _Graphs(_graph(3), _graph(4)))
    assert learned is not None
    assert learned.node("page").fingerprint == ["a", "b"]
    assert learned.node("page").url_paths == ["/page"]


def test_a_version_with_other_checks_does_not_count(
    tmp_path: pathlib.Path,
) -> None:
    _log(tmp_path, _arrival(3, 1), _arrival(3, 2), _arrival(3, 3))
    graphs = _Graphs(_graph(3, "something else"), _graph(4))
    assert apdrift.learn("v", tmp_path, graphs) is None


def test_two_visits_are_not_enough(tmp_path: pathlib.Path) -> None:
    _log(tmp_path, _arrival(4, 1), _arrival(4, 2))
    assert apdrift.learn("v", tmp_path, _Graphs(_graph(4))) is None


def test_another_app_s_arrivals_are_ignored(tmp_path: pathlib.Path) -> None:
    other = {**_arrival(4, 1), "vendor_id": "other"}
    _log(tmp_path, other, other, other)
    assert apdrift.learn("v", tmp_path, _Graphs(_graph(4))) is None
