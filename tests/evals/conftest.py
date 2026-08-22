"""
Opt-in gating for the behavioral evals.

They call the real model (cost, non-determinism, needs an API model
configured), so they are skipped unless ``OPERANT_RUN_LLM_EVALS`` is set.
Run them with:

    OPERANT_RUN_LLM_EVALS=1 uv run pytest tests/evals
"""

from __future__ import annotations

import os
import pathlib
from typing import List

import pytest

import operant.adapters.llm.litellm_client as litecli
import operant.adapters.secrets.env as env
import operant.infra.settings as settings
import operant.ports.llm as plllm
import operant.ports.secrets as pssecret

_ENABLE = "OPERANT_RUN_LLM_EVALS"


def pytest_collection_modifyitems(
    config: pytest.Config, items: List[pytest.Item]
) -> None:
    # Session-wide hook: only skip items in THIS directory, never the
    # unit suite, so `pytest tests` does not silently skip everything.
    if os.environ.get(_ENABLE):
        return
    here = pathlib.Path(__file__).parent
    skip = pytest.mark.skip(reason=f"set {_ENABLE}=1 to run the LLM evals")
    for item in items:
        path = pathlib.Path(str(getattr(item, "fspath", "")))
        if here == path.parent or here in path.parents:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def real_llm() -> plllm.LlmClient:
    """
    The configured litellm client, or skip when none is configured.
    """
    loaded = settings.OperantSettings.load()
    if not loaded.discovery.model:
        pytest.skip("no discovery model configured (set LLM_MODEL)")
    return litecli.LiteLlmClient(loaded.discovery)


@pytest.fixture(scope="session")
def secret_store() -> pssecret.SecretStore:
    return env.EnvSecretStore({})
