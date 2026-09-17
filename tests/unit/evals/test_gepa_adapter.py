"""
GEPA adapter tests with a scripted model.

Cover scores, the placeholder guard, and the reflective records GEPA
reads.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Tuple

import pytest

import operant.adapters.secrets.env as env
import operant.application.discovery.prompt as prompt
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes
import tests.support.llm as sllm

pytest.importorskip("gepa")

# Imported after the skip: the adapter needs the optional gepa extra.
# pylint: disable-next=wrong-import-position
import tests.evals.gepa_adapter as gepaadap  # noqa: E402

Call = Tuple[str, Dict[str, Any]]

_GOOD: List[Call] = [
    ("extract", {"name": "balance", "pattern": r"balance: (\S+)"}),
    ("goal_complete", {"summary": "done"}),
]


def _scenario() -> harness.Scenario:
    return next(
        s
        for s in catalog.FAMILIES["auth"](scenes.SKINS[0])
        if s.name == "already_logged_in"
    )


def _adapter(
    tmp_path: pathlib.Path, calls: List[Call]
) -> gepaadap.OperantAdapter:
    env_ = harness.EvalEnv(sllm.scripted(calls), env.EnvSecretStore({}))
    return gepaadap.OperantAdapter(env_, mode="single", work_dir=tmp_path)


def _first(batch: Any) -> Dict[str, Any]:
    assert batch.trajectories is not None
    return batch.trajectories[0]


def test_a_passing_rollout_scores_one(tmp_path: pathlib.Path) -> None:
    adapter = _adapter(tmp_path, _GOOD)
    batch = adapter.evaluate(
        [_scenario()], gepaadap.seed_candidate("single"), capture_traces=True
    )
    assert batch.scores == [1.0]
    assert _first(batch)["failures"] == []


def test_a_failing_rollout_scores_the_share_of_checks(
    tmp_path: pathlib.Path,
) -> None:
    adapter = _adapter(tmp_path, [("goal_complete", {"summary": "done"})])
    batch = adapter.evaluate(
        [_scenario()], gepaadap.seed_candidate("single"), capture_traces=True
    )
    assert 0.0 < batch.scores[0] < 1.0
    assert any("extracted" in f for f in _first(batch)["failures"])


def test_a_candidate_without_placeholders_scores_zero(
    tmp_path: pathlib.Path,
) -> None:
    adapter = _adapter(tmp_path, _GOOD)
    broken = {
        "executor_prompt": prompt.SYSTEM_PROMPT_TEMPLATE.replace(
            "{secret_names}", "none"
        )
    }
    batch = adapter.evaluate([_scenario()], broken, capture_traces=True)
    assert batch.scores == [0.0]
    assert "placeholders" in _first(batch)["failures"][0]


def test_reflective_records_have_inputs_outputs_and_feedback(
    tmp_path: pathlib.Path,
) -> None:
    adapter = _adapter(tmp_path, [("goal_complete", {"summary": "done"})])
    candidate = gepaadap.seed_candidate("single")
    batch = adapter.evaluate([_scenario()], candidate, capture_traces=True)
    records = adapter.make_reflective_dataset(
        candidate, batch, ["executor_prompt"]
    )
    record = records["executor_prompt"][0]
    assert set(record) >= {"Inputs", "Generated Outputs", "Feedback"}
    assert record["Generated Outputs"] == ["goal_complete"]
    assert "extracted" in record["Feedback"]
