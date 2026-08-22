"""
_commit: a bootstrap run must never overwrite a curated profile.
"""

import pathlib
import shutil

import operant.application.recorder.recording as recdng
import operant.application.usecases.discover as discover
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.infra.repositories.artifacts as artifacts
import operant.infra.repositories.graphs as graphs
import operant.infra.repositories.profiles as profiles
import tests.support.recording as trec

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _profiles(tmp_path: pathlib.Path) -> profiles.FileProfileRepository:
    root = tmp_path / "policies"
    root.mkdir()
    shutil.copy(REPO_ROOT / "policies" / "parabank.json", root / "parabank.json")
    shutil.copy(
        REPO_ROOT / "policies" / "discovery-base.json",
        root / "discovery-base.json",
    )
    return profiles.FileProfileRepository(root, root / "discovery-base.json")


def _parabank_recording() -> recdng.Recording:
    recorder = recdng.Recorder()
    trec.record(
        recorder,
        action=graph.Action(kind="click"),
        control=trec.control("Log In", "button"),
        description="log in",
        pre="Acme",
        post="Acme Home",
    )
    acme = trec.build_recording(recorder, {}, {})
    return discover._rebrand_recording(acme, "acme", "parabank")


def _thin_parabank_profile():
    return trec.PROFILE.model_copy(
        update={
            "vendor_id": "parabank",
            "policy": trec.PROFILE.policy.model_copy(update={"id": "parabank"}),
            "tenants": {"default": artifact.TenantBinding(base_url="http://x")},
            "default_tenant": "default",
        }
    )


def test_bootstrap_collision_saves_generic_and_keeps_curated(
    tmp_path: pathlib.Path,
) -> None:
    profs = _profiles(tmp_path)
    grphs = graphs.FileGraphRepository(tmp_path / "graphs")
    arts = artifacts.FileArtifactRepository(tmp_path / "artifacts")
    result = discover.config.DiscoveryResult(
        recording=_parabank_recording(),
        profile=_thin_parabank_profile(),
    )

    outcome = discover._commit(result, arts, grphs, profs, bootstrap=True)

    curated = profs.get("parabank")
    assert set(curated.tenants) == {"tenant-a", "tenant-b"}
    assert curated.tenants["tenant-b"].secret_refs
    assert profs.exists("parabank-generic")
    assert profs.get("parabank-generic").policy.id == "parabank-generic"
    assert outcome.graph.vendor_id == "parabank-generic"
    assert not grphs.exists("parabank")


def test_profile_mode_saves_in_place(tmp_path: pathlib.Path) -> None:
    profs = _profiles(tmp_path)
    grphs = graphs.FileGraphRepository(tmp_path / "graphs")
    arts = artifacts.FileArtifactRepository(tmp_path / "artifacts")
    result = discover.config.DiscoveryResult(
        recording=_parabank_recording(),
        profile=_thin_parabank_profile(),
    )
    discover._commit(result, arts, grphs, profs, bootstrap=False)
    assert not profs.exists("parabank-generic")
    assert grphs.exists("parabank")
