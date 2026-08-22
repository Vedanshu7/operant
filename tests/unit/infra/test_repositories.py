import json
import pathlib

import pytest

import operant.domain.errors as errors
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as graphs
import operant.infra.repositories.learned_tools as learned_

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _graph(vendor: str = "acme") -> graph.AppGraph:
    source = REPO_ROOT / "graphs" / "parabank" / "v1.json"
    loaded = graph.AppGraph.model_validate_json(source.read_text())
    return loaded.model_copy(
        update={"vendor_id": vendor, "created_at": "", "graph_version": 0}
    )


def _artifact() -> artifact.CapabilityArtifact:
    source = REPO_ROOT / "artifacts" / "goalnative.json"
    return artifact.CapabilityArtifact.model_validate_json(source.read_text())


def test_graph_repository_versions_are_immutable(tmp_path: pathlib.Path) -> None:
    repo = graphs.FileGraphRepository(tmp_path / "graphs")
    assert repo.vendors() == [] and not repo.exists("acme")
    first = repo.save_new_version(_graph())
    second = repo.save_new_version(first)
    assert (first.graph_version, second.graph_version) == (1, 2)
    assert repo.versions("acme") == [1, 2] and repo.head("acme") == 2
    assert repo.get("acme", 1).graph_version == 1
    assert repo.get("acme").graph_version == 2
    assert first.created_at == second.created_at
    assert (tmp_path / "graphs" / "acme" / "HEAD").read_text() == "2\n"
    with pytest.raises(errors.NotFoundError):
        repo.get("acme", 9)
    with pytest.raises(errors.NotFoundError):
        repo.get("nobody")


def test_graph_repository_head_falls_back_to_highest_file(
    tmp_path: pathlib.Path,
) -> None:
    repo = graphs.FileGraphRepository(tmp_path)
    repo.save_new_version(_graph())
    (tmp_path / "acme" / "HEAD").unlink()
    assert repo.head("acme") == 1


def test_artifact_repository_reads_legacy_flat_file_and_migrates_on(
    tmp_path: pathlib.Path,
) -> None:
    repo = raartifa.FileArtifactRepository(tmp_path)
    source = _artifact().model_copy(update={"version": 3})
    (tmp_path / f"{source.id}.json").write_text(source.model_dump_json())
    assert repo.exists(source.id) and repo.head(source.id) == 3
    assert repo.get(source.id).version == 3
    assert repo.ids() == [source.id]
    saved = repo.save_new_version(source)
    assert saved.version == 4
    assert repo.versions(source.id) == [4] and repo.head(source.id) == 4
    assert (tmp_path / source.id / "HEAD").read_text() == "4\n"
    approved = repo.approve(source.id)
    assert approved.status == "approved" and approved.version == 5
    assert repo.get(source.id, 4).status == source.status


def test_learned_tools_store_degrades_to_empty(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state" / "learned-tools.json"
    store = learned_.LearnedToolsStore(path)
    assert store.load() == {}
    store.save({"chrome::login::fill::text_field": "ax-action"})
    assert store.load() == {"chrome::login::fill::text_field": "ax-action"}
    path.write_text("{not json")
    assert store.load() == {}
    path.write_text(json.dumps([1, 2]))
    assert store.load() == {}
