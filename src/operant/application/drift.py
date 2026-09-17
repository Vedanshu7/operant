"""
Learn screens' stable cores from the evidence of verified arrivals.

Capabilities replay on the graph version they are pinned to, so a visit counts
whichever version it ran on, as long as that version judged the node by the
same checks.

Import as:

import operant.application.drift as apdrift
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict, List, Optional, Tuple

import operant.domain.graph.drift as ogdrift
import operant.domain.models.graph as graph
import operant.helpers.logging as logging
import operant.ports.repositories as prepos

_LOG = logging.get_logger(__name__)


def _arrivals(vendor: str, evidence_dir: pathlib.Path) -> List[Dict[str, object]]:
    """
    Read this app's verified arrivals, oldest first.
    """
    found: List[Dict[str, object]] = []
    for log_file in sorted(evidence_dir.glob("*/run-log.jsonl")):
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if '"node_arrived"' in line:
                event = json.loads(line)
                if event.get("vendor_id") == vendor and event.get("at"):
                    found.append(event)
    found.sort(key=lambda event: str(event["at"]))
    return found


def _same_checks(
    node: graph.Node,
    version: int,
    vendor: str,
    graph_store: prepos.GraphRepository,
    versions: Dict[int, graph.AppGraph],
) -> bool:
    """
    Report whether a node had the same checks on another graph version.
    """
    if version not in versions:
        versions[version] = graph_store.get(vendor, version)
    then = next((n for n in versions[version].nodes if n.id == node.id), None)
    return then is not None and then.checks == node.checks


def learn(
    vendor: str,
    evidence_dir: pathlib.Path,
    graph_store: prepos.GraphRepository,
) -> Optional[graph.AppGraph]:
    """
    Save a new graph version from recorded arrivals, when they change it.

    Capabilities stay pinned to the version they were approved on.

    :param vendor: the app.
    :param evidence_dir: where run logs live.
    :param graph_store: versioned graph storage.
    :return: the new version, or ``None`` when nothing changed.
    """
    head = graph_store.get(vendor)
    nodes = {node.id: node for node in head.nodes}
    stored = set(graph_store.versions(vendor))
    versions: Dict[int, graph.AppGraph] = {head.graph_version: head}
    visits: Dict[str, List[List[str]]] = {}
    paths: Dict[str, List[str]] = {}
    for event in _arrivals(vendor, evidence_dir):
        node, version = _visit_of(event, nodes)
        if (
            node is not None
            and version in stored
            and _same_checks(node, version, vendor, graph_store, versions)
        ):
            visits.setdefault(node.id, []).append(list(event["fingerprint"]))  # type: ignore[call-overload]
            if event.get("url_path"):
                paths.setdefault(node.id, []).append(str(event["url_path"]))
    updated = ogdrift.relearn(head, visits, paths)
    if updated is None:
        _LOG.info("no stable change for %s v%s", vendor, head.graph_version)
        return None
    return graph_store.save_new_version(updated)


def _visit_of(
    event: Dict[str, object], nodes: Dict[str, graph.Node]
) -> Tuple[Optional[graph.Node], int]:
    """
    Return the head graph's node an arrival names, and its graph version.
    """
    return nodes.get(str(event.get("node"))), int(
        str(event.get("graph_version", 0))
    )
