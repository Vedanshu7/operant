"""
Behavioral evals for the "auth" prompt rules, over every app skin.

Skipped unless OPERANT_RUN_LLM_EVALS=1; see tests/evals/conftest.py.
"""

from __future__ import annotations

import pathlib

import pytest

import tests.evals.catalog as catalog
import tests.evals.harness as harness

_CASES = catalog.scenarios("auth")


@pytest.mark.parametrize(
    "scenario", [s for _, s in _CASES], ids=[i for i, _ in _CASES]
)
def test_auth(
    tmp_path: pathlib.Path,
    eval_env: harness.EvalEnv,
    scenario: harness.Scenario,
) -> None:
    harness.run_trials(tmp_path, eval_env, scenario)
