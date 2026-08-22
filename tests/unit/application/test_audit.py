"""
The audit gate: every invariant fires on a crafted violation, including a
replica of the shipped goalnative leak (outputs declared, extract empty).
"""

import json
import pathlib
from typing import List, Set

import operant.application.audit
import operant.domain.events as events
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.domain.redaction as redact
import operant.infra.evidence.run_log as run_log
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as graphs

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _node(nid: str) -> graph.Node:
    return graph.Node(
        id=nid, description=nid, checks=[graph.TitleMatches(pattern=nid)]
    )


def _edge(eid: str, from_node: str, to_node: str, **action) -> graph.Edge:
    return graph.Edge.model_validate(
        {
            "id": eid,
            "from": from_node,
            "to": to_node,
            "description": eid,
            "action": action or {"kind": "press", "key": "Enter"},
        }
    )


def _graph_store(tmp_path: pathlib.Path) -> graphs.FileGraphRepository:
    store = graphs.FileGraphRepository(tmp_path / "graphs")
    store.save_new_version(
        graph.AppGraph(
            vendor_id="acme",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[_edge("e1", "a", "b"), _edge("e2", "b", "c")],
        )
    )
    return store


def _cap(**over) -> artifact.CapabilityArtifact:
    base = {
        "id": "cap",
        "name": "cap",
        "description": "d",
        "vendor_id": "acme",
        "graph_version": 1,
        "tenants": {"t": {"base_url": "http://x"}},
        "default_tenant": "t",
        "start_node": "a",
        "goal_node": "c",
        "extract_at_node": "c",
        "compiled_path": ["e1", "e2"],
        "policy_scope": artifact.PolicyScope(
            policy_id="p",
            required_action_kinds=["press"],
            touches_mutating_edges=False,
        ),
        "provenance": artifact.Provenance(
            discovery_run_id="r", model="m", recorded_at="t", goal="g"
        ),
    }
    base.update(over)
    return artifact.CapabilityArtifact.model_validate(base)


def _codes(findings: List[operant.application.audit.Finding]) -> Set[str]:
    return {f.code for f in findings}


def test_clean_artifact_has_no_findings(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    cap = _cap(
        outputs={"x": artifact.OutField(description="x")},
        extract=[artifact.ExtractSpec(output="x", pattern="(x)")],
    )
    assert operant.application.audit.audit_artifact(cap, store) == []


def test_goalnative_leak_replica_is_an_error(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    cap = _cap(
        outputs={"currentBalance": artifact.OutField(description="x")},
        extract=[],
    )
    assert "outputs-uncovered" in _codes(
        operant.application.audit.audit_artifact(cap, store)
    )


def test_output_name_mismatch_is_an_error(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    cap = _cap(
        outputs={"currentBalance": artifact.OutField(description="x")},
        extract=[artifact.ExtractSpec(output="current_balance", pattern="(x)")],
    )
    assert "outputs-uncovered" in _codes(
        operant.application.audit.audit_artifact(cap, store)
    )


def test_missing_graph_version_is_an_error(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    findings = operant.application.audit.audit_artifact(
        _cap(graph_version=9), store
    )
    assert "artifact-graph-missing" in _codes(findings)


def test_unresolvable_and_disconnected_paths(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    assert "compiled-path-unresolvable" in _codes(
        operant.application.audit.audit_artifact(
            _cap(compiled_path=["e1", "gone"]), store
        )
    )
    assert "compiled-path-goal" in _codes(
        operant.application.audit.audit_artifact(
            _cap(compiled_path=["e1"]), store
        )
    )
    assert "compiled-path-disconnected" in _codes(
        operant.application.audit.audit_artifact(
            _cap(compiled_path=["e2", "e1"], start_node="b", goal_node="b"),
            store,
        )
    )


def test_extract_node_off_path_is_an_error(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    store.save_new_version(
        graph.AppGraph(
            vendor_id="acme",
            nodes=[_node("a"), _node("b"), _node("c"), _node("d")],
            edges=[_edge("e1", "a", "b"), _edge("e2", "b", "c")],
        )
    )
    cap = _cap(graph_version=2, extract_at_node="d")
    assert "extract-node-unreached" in _codes(
        operant.application.audit.audit_artifact(cap, store)
    )


def test_undeclared_param_is_an_error(tmp_path: pathlib.Path) -> None:
    store = graphs.FileGraphRepository(tmp_path / "graphs")
    edge = _edge("e1", "a", "b", kind="fill", value={"param": "accountId"})
    store.save_new_version(
        graph.AppGraph(
            vendor_id="acme", nodes=[_node("a"), _node("b")], edges=[edge]
        )
    )
    cap = _cap(
        compiled_path=["e1"], goal_node="b", extract_at_node="b", inputs={}
    )
    assert "params-undeclared" in _codes(
        operant.application.audit.audit_artifact(cap, store)
    )


def test_graph_invariants(tmp_path: pathlib.Path) -> None:
    store = graphs.FileGraphRepository(tmp_path / "graphs")
    bad = graph.AppGraph(
        vendor_id="acme",
        nodes=[_node("a")],
        edges=[
            _edge("e1", "a", "ghost"),
            _edge(
                "e2",
                "a",
                "a",
                kind="invoke",
                graph_ref={"graph_id": "nowhere", "target_node": "n"},
            ),
        ],
    )
    raw = {"edges": [{"id": "e1", "extract": [{"output": "x", "pattern": "x"}]}]}
    codes = _codes(operant.application.audit.audit_graph(bad, raw, store))
    assert {
        "edge-node-unknown",
        "invoke-ref-unresolvable",
        "edge-extract-residue",
    } <= codes


def _fill_edge(literal: str, strategies: List[dict]) -> graph.Edge:
    return graph.Edge.model_validate(
        {
            "id": "e1",
            "from": "a",
            "to": "b",
            "description": "e1",
            "action": {"kind": "fill", "value": {"literal": literal}},
            "target": {"strategies": strategies, "reasoning": "r"},
        }
    )


def test_sensitive_literal_in_a_graph_is_an_error(tmp_path: pathlib.Path) -> None:
    store = graphs.FileGraphRepository(tmp_path / "graphs")
    ssn = _fill_edge(
        "123-45-6789", [{"kind": "role", "role": "text_field", "name": "SSN"}]
    )
    bad = graph.AppGraph(
        vendor_id="acme", nodes=[_node("a"), _node("b")], edges=[ssn]
    )
    findings = operant.application.audit.audit_graph(bad, {}, store)
    assert any(
        f.code == "graph-sensitive-literal"
        and f.severity == "error"
        and "pii" in f.message
        for f in findings
    )
    by_label = _fill_edge(
        "hunter2",
        [
            {
                "kind": "labelProximity",
                "anchor_text": "Password",
                "role": "text_field",
            }
        ],
    )
    assert "graph-sensitive-literal" in _codes(
        operant.application.audit.audit_graph(
            graph.AppGraph(
                vendor_id="acme",
                nodes=[_node("a"), _node("b")],
                edges=[by_label],
            ),
            {},
            store,
        )
    )


def test_notes_body_literal_is_clean(tmp_path: pathlib.Path) -> None:
    store = graphs.FileGraphRepository(tmp_path / "graphs")
    body = _fill_edge(
        "Standup\nblocked on X",
        [
            {
                "kind": "labelProximity",
                "anchor_text": "August 19, 2026 at 4:00 PM",
                "role": "text_area",
            },
        ],
    )
    clean = graph.AppGraph(
        vendor_id="notes", nodes=[_node("a"), _node("b")], edges=[body]
    )
    assert operant.application.audit.audit_graph(clean, {}, store) == []


def test_unclassified_sensitive_io_is_a_warning(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    covered = {
        "outputs": {"x": artifact.OutField(description="x")},
        "extract": [artifact.ExtractSpec(output="x", pattern="(x)")],
    }
    bare = _cap(inputs={"password": artifact.IoField(description="p")}, **covered)
    findings = operant.application.audit.audit_artifact(bare, store)
    assert any(
        f.code == "artifact-unclassified-io" and f.severity == "warning"
        for f in findings
    )
    classified = _cap(
        inputs={
            "password": artifact.IoField(description="p", data_class="credential")
        },
        **covered,
    )
    assert "artifact-unclassified-io" not in _codes(
        operant.application.audit.audit_artifact(classified, store)
    )


def test_repo_graphs_and_artifacts_add_no_errors() -> None:
    findings = operant.application.audit.audit_all(
        raartifa.FileArtifactRepository(REPO_ROOT / "artifacts"),
        graphs.FileGraphRepository(REPO_ROOT / "graphs"),
    )
    errors = {f.code for f in findings if f.severity == "error"}
    assert errors == set(), errors


def test_evidence_legacy_and_blind(tmp_path: pathlib.Path) -> None:
    run = tmp_path / "discovery-1"
    run.mkdir()
    (run / "run-log.jsonl").write_text(
        '{"seq": 0, "type": "discovery_started", "goal": "g"}\n'
    )
    codes = _codes(operant.application.audit.audit_evidence_run(run))
    assert {"legacy-evidence", "discovery-blind"} <= codes
    assert all(
        f.severity == "warning"
        for f in operant.application.audit.audit_evidence_run(run)
    )


def test_evidence_typed_log_is_strictly_validated(tmp_path: pathlib.Path) -> None:
    log = run_log.RunLog(tmp_path, "discovery-2", redact.Redactor(), echo=False)
    log.emit(events.InputDeclared(name="a", value="1"))
    run = tmp_path / "discovery-2"
    with (run / "run-log.jsonl").open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "seq": 99,
                    "type": "input_declared",
                    "name": "x",
                    "value": "1",
                    "type_": "?",
                }
            )
            + "\n"
        )
    codes = _codes(operant.application.audit.audit_evidence_run(run))
    assert "event-invalid" in codes
    assert any(
        f.code == "discovery-blind" and f.severity == "error"
        for f in operant.application.audit.audit_evidence_run(run)
    )


def test_evidence_typed_discovery_with_screenshot_is_clean(
    tmp_path: pathlib.Path,
) -> None:
    log = run_log.RunLog(tmp_path, "discovery-3", redact.Redactor(), echo=False)
    (tmp_path / "discovery-3" / "000-turn-1.png").write_bytes(b"\x89PNG")
    log.emit(events.ScreenshotSaved(file="000-turn-1.png", label="turn-1"))
    assert (
        operant.application.audit.audit_evidence_run(tmp_path / "discovery-3")
        == []
    )


def test_audit_all_flags_approved_unstable(tmp_path: pathlib.Path) -> None:
    store = _graph_store(tmp_path)
    artifacts = raartifa.FileArtifactRepository(tmp_path / "artifacts")
    artifacts.save_new_version(_cap(status="approved"))
    findings = operant.application.audit.audit_all(
        artifacts,
        store,
        stability_of=lambda _cap_id: artifact.Stability(runs=1, successes=0),
    )
    assert "approved-unstable" in _codes(findings)
    proven = operant.application.audit.audit_all(
        artifacts,
        store,
        stability_of=lambda _cap_id: artifact.Stability(runs=5, successes=5),
    )
    assert "approved-unstable" not in _codes(proven)
