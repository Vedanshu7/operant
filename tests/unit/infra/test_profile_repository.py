import pathlib
import shutil

import pytest

import operant.domain.errors as errors
import operant.infra.repositories.profiles as profiles

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _repo(tmp_path: pathlib.Path) -> profiles.FileProfileRepository:
    root = tmp_path / "policies"
    root.mkdir()
    for name in ("parabank.json", "notes.json", "gateway.json"):
        shutil.copy(REPO_ROOT / "policies" / name, root / name)
    shutil.copy(
        REPO_ROOT / "policies" / "discovery-base.json",
        root / "discovery-base.json",
    )
    return profiles.FileProfileRepository(root, root / "discovery-base.json")


def test_lists_only_app_profiles(tmp_path: pathlib.Path) -> None:
    repo = _repo(tmp_path)
    assert repo.ids() == ["notes", "parabank"]
    assert {p.vendor_id for p in repo.list()} == {"notes", "parabank"}
    assert repo.discovery_base().vendor_id


def test_get_and_save_round_trip(tmp_path: pathlib.Path) -> None:
    repo = _repo(tmp_path)
    parabank = repo.get("parabank")
    assert "tenant-b" in parabank.tenants
    updated = parabank.model_copy(
        update={"default_tenant": "tenant-b"}, deep=True
    )
    path = repo.save(updated)
    assert path == repo.path("parabank")
    assert repo.get("parabank").default_tenant == "tenant-b"
    with pytest.raises(errors.NotFoundError):
        repo.get("missing")
