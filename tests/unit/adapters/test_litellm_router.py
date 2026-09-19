"""
Router-config tests, offline via litellm's mock responses.

Roles map to model groups, missing groups fall back to the executor, and
a bad file is a config error.
"""

from __future__ import annotations

import pathlib

import pytest

import operant.adapters.llm.litellm_client as litecli
import operant.domain.errors as errors
import operant.domain.models.llm as llm
import operant.infra.settings as settings

_CONFIG = """
model_list:
  - model_name: executor
    litellm_params:
      model: openai/executor-model
      api_key: fake
      mock_response: "from executor"
  - model_name: reviewer
    litellm_params:
      model: openai/reviewer-model
      api_key: fake
      mock_response: "from reviewer"
router_settings:
  num_retries: 0
"""


def _clients(tmp_path: pathlib.Path, text: str = _CONFIG) -> litecli.ModelClients:
    path = tmp_path / "router.yml"
    path.write_text(text)
    return litecli.build_clients(settings.DiscoverySettings(router_config=path))


def _ask(client: litecli.LiteLlmClient) -> str:
    turn = client.complete([llm.ChatMessage(role="user", content="hi")], tools=[])
    return turn.content


def test_each_role_calls_its_model_group(tmp_path: pathlib.Path) -> None:
    clients = _clients(tmp_path)
    assert _ask(clients.executor) == "from executor"
    assert _ask(clients.roles["verifier"]) == "from reviewer"
    assert clients.models["safety"] == "openai/reviewer-model"


def test_a_missing_group_falls_back_to_the_executor(
    tmp_path: pathlib.Path,
) -> None:
    clients = _clients(tmp_path)
    assert _ask(clients.roles["planner"]) == "from executor"
    assert clients.models["planner"] == "openai/executor-model"


def test_a_config_without_an_executor_group_is_rejected(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(errors.ConfigError):
        _clients(
            tmp_path, _CONFIG.replace("model_name: executor", "model_name: x")
        )


def test_an_unreadable_config_is_a_config_error(tmp_path: pathlib.Path) -> None:
    config = settings.DiscoverySettings(router_config=tmp_path / "missing.yml")
    with pytest.raises(errors.ConfigError):
        litecli.build_clients(config)


def test_without_a_router_roles_use_the_per_role_models() -> None:
    clients = litecli.build_clients(
        settings.DiscoverySettings(model="m-exec", verifier_model="m-review")
    )
    assert clients.models == {
        "executor": "m-exec",
        "planner": "m-exec",
        "verifier": "m-review",
        "safety": "m-review",
        "extract": "m-review",
        "critic": "m-review",
        "schema": "m-review",
        "gate": "m-review",
    }


def test_the_shipped_router_config_loads() -> None:
    path = pathlib.Path(__file__).resolve().parents[3] / "router.yml"
    clients = litecli.build_clients(
        settings.DiscoverySettings(router_config=path)
    )
    assert set(clients.roles) == set(litecli.ROLE_GROUPS) - {"executor"}


def test_every_request_asks_for_one_tool_call(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def fake_completion(**kwargs: object) -> object:
        seen.append(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(litecli.litellm, "completion", fake_completion)
    client = litecli.LiteLlmClient(settings.DiscoverySettings(model="m"))
    with pytest.raises(errors.LlmError):
        client.complete([llm.ChatMessage(role="user", content="hi")], tools=[])
    assert seen[0]["parallel_tool_calls"] is False
    assert seen[0]["timeout"] == 60.0
