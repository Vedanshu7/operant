"""
The typer CLI over pure commands: version, doctor, catalog, audit, graph.

These exercise the command wiring against a temporary data root - no
live surface, no model.
"""

import json
import pathlib

import typer.testing as testing

import operant.cli.main as main
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as rggraphs

runner = testing.CliRunner()


def _seed(root: pathlib.Path) -> None:
    (root / "policies").mkdir(parents=True, exist_ok=True)
    graphs = rggraphs.FileGraphRepository(root / "graphs")
    graphs.save_new_version(
        graph.AppGraph(
            vendor_id="acme",
            nodes=[
                graph.Node(
                    id="a",
                    description="a",
                    checks=[graph.TitleMatches(pattern="a")],
                ),
                graph.Node(
                    id="b",
                    description="b",
                    checks=[graph.TitleMatches(pattern="b")],
                ),
            ],
            edges=[
                graph.Edge.model_validate(
                    {
                        "id": "e1",
                        "from": "a",
                        "to": "b",
                        "description": "go",
                        "action": {"kind": "press", "key": "Enter"},
                    }
                )
            ],
        )
    )
    artifacts = raartifa.FileArtifactRepository(root / "artifacts")
    artifacts.save_new_version(
        artifact.CapabilityArtifact.model_validate(
            {
                "id": "demo",
                "name": "demo",
                "description": "a demo capability",
                "vendor_id": "acme",
                "graph_version": 1,
                "tenants": {"t": {"base_url": "http://x"}},
                "default_tenant": "t",
                "start_node": "a",
                "goal_node": "b",
                "extract_at_node": "b",
                "compiled_path": ["e1"],
                "policy_scope": {
                    "policy_id": "acme",
                    "required_action_kinds": ["press"],
                    "touches_mutating_edges": False,
                },
                "provenance": {
                    "discovery_run_id": "r",
                    "model": "m",
                    "recorded_at": "t",
                    "goal": "g",
                },
            }
        )
    )


def _invoke(root: pathlib.Path, *args: str):
    return runner.invoke(main.app, ["--root", str(root), *args])


def test_version() -> None:
    result = runner.invoke(main.app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_doctor_reports_config(tmp_path: pathlib.Path) -> None:
    result = _invoke(tmp_path, "doctor")
    assert result.exit_code == 0
    assert "secrets backend: env" in result.stdout


def test_catalog_and_graph_list(tmp_path: pathlib.Path) -> None:
    _seed(tmp_path)
    catalog = _invoke(tmp_path, "catalog", "list")
    assert catalog.exit_code == 0 and "demo v1" in catalog.stdout
    graphs = _invoke(tmp_path, "graph", "list")
    assert graphs.exit_code == 0 and "acme: v1" in graphs.stdout


def test_audit_is_clean_on_seeded_data(tmp_path: pathlib.Path) -> None:
    _seed(tmp_path)
    result = _invoke(tmp_path, "audit")
    assert result.exit_code == 0
    assert "0 error(s)" in result.stdout


def test_catalog_approve_refuses_unproven_then_forces(
    tmp_path: pathlib.Path,
) -> None:
    _seed(tmp_path)
    refused = _invoke(tmp_path, "catalog", "approve", "demo")
    assert refused.exit_code == 1
    forced = _invoke(tmp_path, "catalog", "approve", "demo", "--force")
    assert forced.exit_code == 0 and "approved" in forced.stdout


def test_migrate_versions_a_flat_artifact(tmp_path: pathlib.Path) -> None:
    (tmp_path / "artifacts").mkdir(parents=True)
    flat = {
        "id": "legacy",
        "name": "legacy",
        "description": "d",
        "vendor_id": "acme",
        "graph_version": 1,
        "version": 2,
        "tenants": {"t": {"base_url": "http://x"}},
        "default_tenant": "t",
        "start_node": "a",
        "goal_node": "b",
        "compiled_path": [],
        "policy_scope": {
            "policy_id": "acme",
            "required_action_kinds": [],
            "touches_mutating_edges": False,
        },
        "provenance": {
            "discovery_run_id": "r",
            "model": "m",
            "recorded_at": "t",
            "goal": "g",
        },
    }
    (tmp_path / "artifacts" / "legacy.json").write_text(json.dumps(flat))
    result = _invoke(tmp_path, "migrate")
    assert result.exit_code == 0
    assert (tmp_path / "artifacts" / "legacy" / "HEAD").exists()
