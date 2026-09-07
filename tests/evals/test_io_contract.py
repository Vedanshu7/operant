"""
Behavioral evals for the "io" prompt rules, over every app skin.

Skipped unless OPERANT_RUN_LLM_EVALS=1; see tests/evals/conftest.py.
"""

from __future__ import annotations

import pathlib

import pytest

import operant.ports.llm as plllm
import operant.ports.secrets as pssecret
import tests.evals.catalog as catalog
import tests.evals.harness as harness

_CASES = catalog.scenarios("io")


@pytest.mark.parametrize(
    "scenario", [s for _, s in _CASES], ids=[i for i, _ in _CASES]
)
def test_io(
    tmp_path: pathlib.Path,
    real_llm: plllm.LlmClient,
    secret_store: pssecret.SecretStore,
    scenario: harness.Scenario,
) -> None:
    harness.run_trials(tmp_path, real_llm, secret_store, scenario)
