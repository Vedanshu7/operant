"""
The replay use case runs under the configured engine timings.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict

import pytest

import operant.application.replay.traverse as traverse
import operant.application.usecases.replay as replay
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import tests.support.server as server
import tests.support.settings as tssettin


def test_engine_settings_reach_the_replay(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = tssettin.test_settings(tmp_path)
    settings.engine.total_timeout_s = 7.0
    settings.engine.settle_ms = 123
    settings.engine.max_invoke_depth = 2
    capability_id = server.seed(settings)
    seen: Dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> object:
        seen["options"] = args[6]
        seen["depth"] = kwargs["max_invoke_depth"]
        raise RuntimeError("stop after wiring")

    monkeypatch.setattr(traverse, "run_capability", capture)
    with pytest.raises(RuntimeError):
        replay.execute_replay(
            replay.ReplayRequest(capability_id=capability_id),
            factory=server.ScriptedFactory(settings),
            artifacts=raartifa.FileArtifactRepository(
                settings.paths.artifacts_dir
            ),
            graphs=rggraphs.FileGraphRepository(settings.paths.graphs_dir),
            profiles=rpprofil.FileProfileRepository(
                settings.paths.policies_dir, settings.paths.discovery_base_profile
            ),
        )
    assert seen["options"].total_timeout_s == 7.0
    assert seen["options"].settle_ms == 123
    assert seen["depth"] == 2
