"""
Invariant checks over the persisted world: artifacts, graphs, evidence.

The incidents this gate exists for actually shipped: a capability with
an empty extract list "succeeded" on specs leaked from a shared graph
edge, and an untyped kwarg corrupted every ``input_declared`` event
while discovery ran blind (zero screenshots) without a single log line.
Every check below names the class of failure it makes impossible to miss
again.

Stability lives in SQLite now, so the approved-unstable check reads it
through an injected ``stability_of`` callable rather than the artifact.

Import as:

import operant.application.audit as aaaudit
"""

from __future__ import annotations

import collections.abc
import dataclasses
import itertools
import json
import pathlib
import re
from typing import Any, Dict, Final, List, Literal, Optional, Set

import pydantic

import operant.domain.events as events
import operant.domain.governance as govern
import operant.domain.graph.pathfind as pathfind
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as mggraph
import operant.domain.models.targets as targets
import operant.domain.sensitivity as sensv
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as graphs

_PARAM_RE: Final = re.compile(r"\{\{(\w+)\}\}")

StabilityOf = collections.abc.Callable[[str], artifact.Stability]


# #############################################################################
# Finding
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Finding:
    """
    One audit finding.

    :ivar severity:``error`` blocks a strict audit; ``warning`` does
        not.
    :ivar code: Stable machine-readable finding code.
    :ivar subject: The file or run the finding is about.
    :ivar message: Human-readable explanation.
    """

    severity: Literal["error", "warning"]
    code: str
    subject: str
    message: str


def _zero_stability(_capability_id: str) -> artifact.Stability:
    """
    Report zero stability (default source: nothing recorded).
    """
    stability = artifact.Stability(runs=0, successes=0)
    return stability


def audit_all(
    artifact_store: raartifa.FileArtifactRepository,
    graph_store: graphs.FileGraphRepository,
    evidence_root: Optional[pathlib.Path] = None,
    *,
    stability_of: StabilityOf = _zero_stability,
    gate: Optional[govern.StabilityGate] = None,
) -> List[Finding]:
    """
    Audits every artifact, graph version, and evidence run.

    :param artifact_store: Where capabilities live.
    :param graph_store: Where graph versions live.
    :param evidence_root: Evidence directory to validate; skipped if
        ``None``.
    :param stability_of: Returns a capability's replay track record.
    :param gate: The approval gate; defaults to the governance default.
    :return: Findings, errors and warnings interleaved in scan order.
    """
    gate = gate or govern.StabilityGate()
    findings: List[Finding] = []
    for cap in artifact_store.list():
        findings += audit_artifact(cap, graph_store)
        findings += _audit_stability(cap, stability_of(cap.id), gate)
    findings += _audit_graphs(graph_store)
    if evidence_root is not None and evidence_root.exists():
        for run_dir in sorted(p for p in evidence_root.iterdir() if p.is_dir()):
            findings += audit_evidence_run(run_dir)
    return findings


def _audit_stability(
    cap: artifact.CapabilityArtifact,
    stability: artifact.Stability,
    gate: govern.StabilityGate,
) -> List[Finding]:
    """
    Warn when an approved capability fails the stability gate.
    """
    findings: List[Finding] = []
    if cap.status == "approved" and not gate.passes(
        stability.runs, stability.successes
    ):
        findings.append(
            Finding(
                "warning",
                "approved-unstable",
                f"artifacts/{cap.id}",
                f"approved with stability {stability.successes}/{stability.runs}"
                f" ({gate.describe(stability.runs, stability.successes)})",
            )
        )
    return findings


def _audit_graphs(
    graph_store: graphs.FileGraphRepository,
) -> List[Finding]:
    """
    Audit every stored graph version.
    """
    findings: List[Finding] = []
    for vendor_id in graph_store.vendors():
        for version in graph_store.versions(vendor_id):
            path = graph_store.path(vendor_id, version)
            raw = json.loads(path.read_text(encoding="utf-8"))
            graph = mggraph.AppGraph.model_validate(raw)
            findings += audit_graph(graph, raw, graph_store)
    return findings


def audit_artifact(
    cap: artifact.CapabilityArtifact,
    graph_store: graphs.FileGraphRepository,
) -> List[Finding]:
    """
    Check one capability against the graph version it pins.
    """
    subject = f"artifacts/{cap.id}"
    try:
        graph = graph_store.get(cap.vendor_id, cap.graph_version)
    except Exception as err:
        # A missing pinned graph is itself the finding.
        findings = [
            Finding(
                "error",
                "artifact-graph-missing",
                subject,
                f"pinned graph {cap.vendor_id} v{cap.graph_version} "
                f"cannot be loaded: {err}",
            )
        ]
    else:
        # Graph loaded: run the node, path, and IO checks.
        findings = _audit_nodes(cap, graph, subject)
        findings += _audit_compiled_path(cap, graph, subject)
        findings += _audit_io(cap, subject)
    return findings


def _audit_nodes(
    cap: artifact.CapabilityArtifact,
    graph: mggraph.AppGraph,
    subject: str,
) -> List[Finding]:
    """
    Check the capability's named nodes exist in the graph.
    """
    findings: List[Finding] = []
    node_ids = {n.id for n in graph.nodes}
    named = (
        ("start_node", cap.start_node),
        ("goal_node", cap.goal_node),
        ("extract_at_node", cap.extract_at_node),
    )
    for label, node in named:
        if node and node != "*" and node not in node_ids:
            findings.append(
                Finding(
                    "error",
                    "artifact-node-unknown",
                    subject,
                    f"{label} {node!r} is not in graph {cap.vendor_id} "
                    f"v{cap.graph_version}",
                )
            )
    return findings


def _audit_compiled_path(
    cap: artifact.CapabilityArtifact,
    graph: mggraph.AppGraph,
    subject: str,
) -> List[Finding]:
    """
    Check the compiled path resolves, connects, and flows data.
    """
    findings: List[Finding] = []
    edges = (
        pathfind.compiled_edges(graph, cap.compiled_path)
        if cap.compiled_path
        else []
    )
    if cap.compiled_path and edges is None:
        # Named edges that don't resolve: report and stop.
        findings = [
            Finding(
                "error",
                "compiled-path-unresolvable",
                subject,
                "compiled_path names edges missing from graph "
                f"v{cap.graph_version}",
            )
        ]
    elif edges:
        # Path resolved: audit its shape and dataflow.
        findings += _audit_path_shape(cap, edges, subject)
        findings += _audit_path_dataflow(cap, edges, subject)
    return findings


def _audit_path_shape(
    cap: artifact.CapabilityArtifact,
    edges: List[mggraph.Edge],
    subject: str,
) -> List[Finding]:
    """
    Check the path's endpoints, continuity, and extract node.
    """
    findings: List[Finding] = []
    if cap.start_node != "*" and edges[0].from_node != cap.start_node:
        findings.append(
            Finding(
                "error",
                "compiled-path-start",
                subject,
                f"path starts at {edges[0].from_node!r}, artifact says "
                f"{cap.start_node!r}",
            )
        )
    for prev, nxt in itertools.pairwise(edges):
        if nxt.from_node != prev.to_node:
            findings.append(
                Finding(
                    "error",
                    "compiled-path-disconnected",
                    subject,
                    f"edge {nxt.id} starts at {nxt.from_node!r} but "
                    f"{prev.id} ends at {prev.to_node!r}",
                )
            )
    if edges[-1].to_node != cap.goal_node:
        findings.append(
            Finding(
                "error",
                "compiled-path-goal",
                subject,
                f"path ends at {edges[-1].to_node!r}, goal is "
                f"{cap.goal_node!r}",
            )
        )
    visited = {edges[0].from_node} | {e.to_node for e in edges}
    if cap.extract_at_node and cap.extract_at_node not in visited:
        findings.append(
            Finding(
                "error",
                "extract-node-unreached",
                subject,
                f"extract_at_node {cap.extract_at_node!r} is never visited "
                "by the compiled path",
            )
        )
    return findings


def _audit_path_dataflow(
    cap: artifact.CapabilityArtifact,
    edges: List[mggraph.Edge],
    subject: str,
) -> List[Finding]:
    """
    Check the path's parameters and consumed outputs are declared.
    """
    findings: List[Finding] = []
    needed: Set[str] = set().union(*(_edge_params(e) for e in edges))
    undeclared = needed - set(cap.inputs)
    if undeclared:
        findings.append(
            Finding(
                "error",
                "params-undeclared",
                subject,
                f"path references parameters {sorted(undeclared)} not "
                "declared as inputs",
            )
        )
    flows = {
        e.action.value.from_output
        for e in edges
        if e.action.value is not None and e.action.value.from_output is not None
    }
    unflowed = flows - set(cap.outputs)
    if unflowed:
        findings.append(
            Finding(
                "error",
                "from-output-undeclared",
                subject,
                f"path consumes outputs {sorted(unflowed)} the capability "
                "never extracts",
            )
        )
    expected_kinds = sorted({e.action.kind for e in edges})
    if cap.policy_scope.required_action_kinds != expected_kinds:
        findings.append(
            Finding(
                "warning",
                "policy-scope-drift",
                subject,
                "policy_scope.required_action_kinds "
                f"{cap.policy_scope.required_action_kinds} != path kinds "
                f"{expected_kinds}",
            )
        )
    return findings


def _audit_io(cap: artifact.CapabilityArtifact, subject: str) -> List[Finding]:
    """
    Check declared outputs are covered and IO sensitivity is classified.
    """
    findings: List[Finding] = []
    uncovered = set(cap.outputs) - {s.output for s in cap.extract}
    if uncovered:
        findings.append(
            Finding(
                "error",
                "outputs-uncovered",
                subject,
                f"declared outputs {sorted(uncovered)} have no extract spec "
                "on this capability (it would only ever 'succeed' via specs "
                "leaked from elsewhere)",
            )
        )
    for kind, fields in (("input", cap.inputs), ("output", cap.outputs)):
        for name, spec in fields.items():
            guess = sensv.classify(name=name)
            if spec.data_class == "none" and sensv.is_sensitive(guess):
                findings.append(
                    Finding(
                        "warning",
                        "artifact-unclassified-io",
                        subject,
                        f'{kind} "{name}" looks {guess} but has data_class '
                        '"none" (re-record, or classify it by hand)',
                    )
                )
    return findings


def _edge_params(edge: mggraph.Edge) -> Set[str]:
    """
    Collect the parameter names an edge references.
    """
    found: Set[str] = set()
    value = edge.action.value
    if value is not None and value.param is not None:
        found.add(value.param)
    if edge.target is not None:
        for s in edge.target.strategies:
            if isinstance(s, targets.RoleStrategy):
                found |= set(_PARAM_RE.findall(s.name))
            elif isinstance(s, targets.LabelProximityStrategy):
                found |= set(_PARAM_RE.findall(s.anchor_text))
    return found


def audit_graph(
    graph: mggraph.AppGraph,
    raw: Dict[str, Any],
    graph_store: graphs.FileGraphRepository,
) -> List[Finding]:
    """
    Check one immutable graph version.
    """
    subject = f"graphs/{graph.vendor_id}/v{graph.graph_version}.json"
    findings: List[Finding] = []
    node_ids = {n.id for n in graph.nodes}
    for edge in graph.edges:
        findings += _audit_edge(edge, node_ids, graph_store, subject)
    for outcome in graph.outcome_edges:
        findings += _audit_outcome_edge(outcome, node_ids, graph_store, subject)
    for edge_dict in raw.get("edges", []):
        if edge_dict.get("extract"):
            findings.append(
                Finding(
                    "warning",
                    "edge-extract-residue",
                    subject,
                    f"edge {edge_dict.get('id')} carries pre-2.1 edge-scoped "
                    "extract specs (ignored on load; re-record to clean)",
                )
            )
    return findings


def _audit_edge(
    edge: mggraph.Edge,
    node_ids: Set[str],
    graph_store: graphs.FileGraphRepository,
    subject: str,
) -> List[Finding]:
    """
    Check one edge's nodes, invoke ref, and fill literals.
    """
    findings: List[Finding] = []
    for end, node in (("from", edge.from_node), ("to", edge.to_node)):
        if node not in node_ids:
            findings.append(
                Finding(
                    "error",
                    "edge-node-unknown",
                    subject,
                    f"edge {edge.id} {end}-node {node!r} does not exist",
                )
            )
    if edge.action.kind == "invoke":
        ref = edge.action.graph_ref
        if ref is None:
            # No graph_ref at all on the invoke edge.
            findings.append(
                Finding(
                    "error",
                    "invoke-ref-missing",
                    subject,
                    f"invoke edge {edge.id} has no graph_ref",
                )
            )
        elif not graph_store.exists(ref.graph_id):
            # Ref names a graph that does not exist.
            findings.append(
                Finding(
                    "error",
                    "invoke-ref-unresolvable",
                    subject,
                    f"edge {edge.id} invokes unknown graph {ref.graph_id!r}",
                )
            )
    literal_class = _fill_literal_class(edge)
    if sensv.is_sensitive(literal_class):
        findings.append(
            Finding(
                "error",
                "graph-sensitive-literal",
                subject,
                f"edge {edge.id} persists a {literal_class} value as a fill "
                "literal (re-record: sensitive literals become inputs)",
            )
        )
    return findings


def _audit_outcome_edge(
    outcome: mggraph.OutcomeEdge,
    node_ids: Set[str],
    graph_store: graphs.FileGraphRepository,
    subject: str,
) -> List[Finding]:
    """
    Check one outcome edge's node and invoke ref.
    """
    findings: List[Finding] = []
    if outcome.at != "*" and outcome.at not in node_ids:
        findings.append(
            Finding(
                "error",
                "outcome-node-unknown",
                subject,
                f"outcome edge {outcome.id} is scoped to unknown node "
                f"{outcome.at!r}",
            )
        )
    handle = outcome.handle
    if isinstance(handle, mggraph.InvokeGraphHandle) and not graph_store.exists(
        handle.ref.graph_id
    ):
        findings.append(
            Finding(
                "error",
                "invoke-ref-unresolvable",
                subject,
                f"outcome edge {outcome.id} invokes unknown graph "
                f"{handle.ref.graph_id!r}",
            )
        )
    return findings


def _fill_literal_class(edge: mggraph.Edge) -> Optional[str]:
    """
    Classify a persisted fill literal by its target's semantics.
    """
    value = edge.action.value
    literal_class: Optional[str] = None
    if (
        edge.action.kind == "fill"
        and value is not None
        and value.literal is not None
    ):
        name = label = role = None
        strategies = edge.target.strategies if edge.target is not None else ()
        for s in strategies:
            if isinstance(s, targets.RoleStrategy) and name is None:
                name, role = s.name, s.role
            elif isinstance(s, targets.LabelProximityStrategy) and label is None:
                label, role = s.anchor_text, role or s.role
        literal_class = sensv.classify(
            name=name, label=label, control_role=role, value=value.literal
        )
    return literal_class


def audit_evidence_run(run_dir: pathlib.Path) -> List[Finding]:
    """
    Validate one evidence run's log and screenshot presence.
    """
    subject = str(run_dir)
    log_path = run_dir / "run-log.jsonl"
    if not log_path.exists():
        return [
            Finding(
                "warning",
                "evidence-no-log",
                subject,
                "run directory has no run-log.jsonl",
            )
        ]
    lines = log_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return [
            Finding(
                "warning", "evidence-no-log", subject, "run-log.jsonl is empty"
            )
        ]
    first = _parse(lines[0])
    legacy = not (isinstance(first, dict) and first.get("type") == "run_meta")
    findings: List[Finding] = []
    if legacy:
        findings.append(
            Finding(
                "warning",
                "legacy-evidence",
                subject,
                "pre-typed-events log (no run_meta header); schema not "
                "enforced",
            )
        )
    shots = _audit_lines(lines, subject, findings, legacy=legacy)
    if run_dir.name.startswith("discovery-"):
        on_disk = [
            f
            for f in shots
            if (run_dir / f).is_file() and (run_dir / f).stat().st_size > 0
        ]
        if not on_disk:
            findings.append(
                Finding(
                    "warning" if legacy else "error",
                    "discovery-blind",
                    subject,
                    "discovery run has no saved screenshot - the agent ran "
                    "without vision",
                )
            )
    return findings


def _audit_lines(
    lines: List[str],
    subject: str,
    findings: List[Finding],
    *,
    legacy: bool,
) -> List[str]:
    """
    Validate each log line and collect logged screenshot files.
    """
    shots_logged: List[str] = []
    for i, line in enumerate(lines):
        entry = _parse(line)
        if entry is None:
            findings.append(
                Finding(
                    "warning" if legacy else "error",
                    "event-unparsable",
                    subject,
                    f"line {i + 1} is not valid JSON",
                )
            )
            continue
        if not legacy:
            try:
                events.event_adapter.validate_python(entry)
            except pydantic.ValidationError as err:
                findings.append(
                    Finding(
                        "error",
                        "event-invalid",
                        subject,
                        f"line {i + 1} ({entry.get('type', '?')}): "
                        f"{err.errors()[0].get('msg')}",
                    )
                )
        if entry.get("type") == "screenshot_saved":
            shots_logged.append(str(entry.get("file", "")))
    return shots_logged


def _parse(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse one log line into a dict, or None.
    """
    result: Optional[Dict[str, Any]] = None
    try:
        entry = json.loads(line)
    except ValueError:
        entry = None
    if isinstance(entry, dict):
        result = entry
    return result
