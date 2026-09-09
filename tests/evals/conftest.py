"""
Opt-in gating, fixtures and the results summary for the behavioral evals.

They call the real model (cost, non-determinism, needs an API model
configured), so they are skipped unless ``OPERANT_RUN_LLM_EVALS`` is set.
Run them with:

    OPERANT_RUN_LLM_EVALS=1 uv run pytest tests/evals

``OPERANT_EVAL_TRIALS`` and ``OPERANT_EVAL_PASS_RATE`` tune the trials;
every trial is appended to ``state/evals/<session>.jsonl``.
"""

from __future__ import annotations

import collections
import collections.abc
import os
import pathlib
from typing import Any, Dict, List, Tuple

import litellm
import pytest

import operant.adapters.llm.litellm_client as litecli
import operant.adapters.observability.factory as aofactor
import operant.adapters.privacy.factory as apfactor
import operant.adapters.secrets.env as env
import operant.infra.settings as settings
import operant.ports.llm as plllm
import operant.ports.secrets as pssecret
import tests.evals.harness as harness
import tests.evals.trajectory as trajecto

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
    Return the configured litellm client; skip without a model or key.
    """
    loaded = settings.OperantSettings.load()
    clients = litecli.build_clients(loaded.discovery)
    model = clients.models["executor"]
    if not model:
        pytest.skip(
            "no discovery model configured (set OPERANT_DISCOVERY__MODEL)"
        )
    env_check: Dict[str, Any] = litellm.validate_environment(model=model)
    if not loaded.discovery.api_key and not env_check.get("keys_in_environment"):
        pytest.skip(
            f"no API key for {model}: set {env_check.get('missing_keys')}"
        )
    return clients.executor


@pytest.fixture(scope="session")
def secret_store() -> pssecret.SecretStore:
    return env.EnvSecretStore({})


@pytest.fixture(scope="session")
def eval_env(
    real_llm: plllm.LlmClient, secret_store: pssecret.SecretStore
) -> collections.abc.Iterator[harness.EvalEnv]:
    """
    Bundle the model, tracer and scrubber every trial runs with.

    Traces go to Langfuse when
    ``OPERANT_OBSERVABILITY__BACKEND=langfuse``; the scrubber follows
    ``OPERANT_PRIVACY__*`` (Presidio when installed).
    """
    loaded = settings.OperantSettings.load()
    tracer = aofactor.tracer(loaded.observability)
    bundle = harness.EvalEnv(
        llm=real_llm,
        secret_store=secret_store,
        tracer=tracer,
        scrubber=apfactor.scrubber(loaded.privacy),
        # The planner and reviewers use their own Router groups, if any.
        role_llms=dict(litecli.build_clients(loaded.discovery).roles),
    )
    yield bundle
    tracer.flush()


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """
    Print a pass-rate table per scenario and where the rows were written.
    """
    if not harness.SUMMARY:
        return
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = (
        collections.defaultdict(list)
    )
    for row in harness.SUMMARY:
        groups[(row["family"], row["scenario"], row["mode"])].append(row)
    write = terminalreporter.write_line
    write("")
    write(
        f"{'family':<10} {'scenario':<26} {'mode':<7} {'pass':>7} "
        f"{'turns':>6} {'tokens':>8} {'effic':>6}"
    )
    for (family, scenario, mode), rows in sorted(groups.items()):
        passed = sum(1 for r in rows if r["passed"])
        turns = sum(r["turns"] for r in rows) / len(rows)
        tokens = sum(r["tokens_in"] + r["tokens_out"] for r in rows) / len(rows)
        efficiency = trajecto.summarize(rows)["efficiency"]
        write(
            f"{family:<10} {scenario:<26} {mode:<7} {passed:>3}/{len(rows):<3} "
            f"{turns:>6.1f} {tokens:>8.0f} {efficiency:>6.2f}"
        )
    verifier = trajecto.summarize(harness.SUMMARY)
    write(
        "verifier (goal claims): "
        f"{verifier['true_accept']:.0f} true accept, "
        f"{verifier['false_accept']:.0f} false accept, "
        f"{verifier['true_reject']:.0f} true reject, "
        f"{verifier['false_reject']:.0f} false reject"
    )
    write(f"results: {harness.RESULTS_DIR / (harness.SESSION + '.jsonl')}")
