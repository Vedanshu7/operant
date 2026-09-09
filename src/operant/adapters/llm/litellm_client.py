"""
Litellm-backed chat completion.

Multi-provider: ``anthropic/...``, ``openai/...``, or any OpenAI-
compatible endpoint via the configured api base. Models come either from
settings, or - for per-role models, fallbacks and timeouts - from a
litellm Router config file (``OPERANT_DISCOVERY__ROUTER_CONFIG``) whose
model groups are named after the agent roles.
Retrying lives in the discovery loop, which logs each failed attempt as
evidence; this client maps one failure to one ``LlmError``.

Import as:

import operant.adapters.llm.litellm_client as litecli
"""

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
from typing import Any, Dict, Final, Optional

import litellm
import yaml

import operant.domain.errors as errors
import operant.domain.models.llm as llm
import operant.infra.settings as settings

# #############################################################################
# LiteLlmClient
# #############################################################################


class LiteLlmClient:
    """
    Implement ``operant.ports.llm.LlmClient`` over litellm.
    """

    def __init__(
        self,
        config: settings.DiscoverySettings,
        *,
        router: Optional[litellm.Router] = None,
        alias: str = "executor",
    ) -> None:
        """
        Call one model directly, or one model group through a Router.

        :param config: The discovery settings group.
        :param router: A Router built from the router config, if any.
        :param alias: The Router model group this client calls.
        :raises errors.ConfigError: Without a router and without a
            model.
        """
        if router is None and not config.model:
            raise errors.ConfigError(
                "no discovery model configured (set OPERANT_DISCOVERY__MODEL, "
                "or OPERANT_DISCOVERY__ROUTER_CONFIG)"
            )
        self._router = router
        self._alias = alias
        self._model = config.model or ""
        self._api_base = config.api_base
        self._api_key = (
            config.api_key.get_secret_value() if config.api_key else None
        )
        self._timeout = config.request_timeout_s

    def complete(
        self,
        messages: collections.abc.Sequence[llm.ChatMessage],
        *,
        tools: collections.abc.Sequence[llm.ToolSchema],
    ) -> llm.LlmTurn:
        """
        Run one completion with tool calling required.
        """
        request: Dict[str, Any] = {
            "messages": [_encode_message(m) for m in messages],
            "tools": [_encode_tool(t) for t in tools],
            "tool_choice": "required",
            # The loop runs one action per turn; without this, models batch
            # several calls and every call after the first is discarded.
            "parallel_tool_calls": False,
            # Providers without the option ignore it instead of failing.
            "drop_params": True,
        }
        try:
            if self._router is not None:
                # The Router applies the group's timeout, retries, fallbacks.
                response = self._router.completion(model=self._alias, **request)
            else:
                # A bounded request: a stalled call must not hang the run.
                response = litellm.completion(
                    model=self._model,
                    api_base=self._api_base,
                    api_key=self._api_key,
                    timeout=self._timeout,
                    **request,
                )
        # Provider SDKs raise many concrete types.
        except Exception as err:
            auth_error = getattr(litellm, "AuthenticationError", ())
            retryable = not isinstance(err, auth_error)
            raise errors.LlmError(str(err), retryable=retryable) from err
        turn = _decode_turn(response)
        return turn


def _encode_message(message: llm.ChatMessage) -> Dict[str, Any]:
    """
    Encode a chat message into the litellm wire shape.
    """
    encoded: Dict[str, Any] = {"role": message.role}
    if isinstance(message.content, str):
        # A plain string is sent as-is.
        encoded["content"] = message.content
    else:
        # Structured content becomes a list of encoded parts.
        encoded["content"] = [_encode_part(part) for part in message.content]
    if message.tool_calls:
        encoded["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        encoded["tool_call_id"] = message.tool_call_id
    return encoded


def _encode_part(part: llm.ContentPart) -> Dict[str, Any]:
    """
    Encode one content part as text or image_url.
    """
    encoded: Dict[str, Any]
    if part.type == "text":
        # A text part.
        encoded = {"type": "text", "text": part.text}
    else:
        # An image part carries its URL or data URI.
        encoded = {"type": "image_url", "image_url": {"url": part.image_url}}
    return encoded


def _encode_tool(tool: llm.ToolSchema) -> Dict[str, Any]:
    """
    Encode a tool schema as a litellm function tool.
    """
    encoded = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
    return encoded


def _decode_turn(response: Any) -> llm.LlmTurn:
    """
    Decode a litellm response into an ``LlmTurn``.
    """
    message = response.choices[0].message
    calls = tuple(
        llm.ToolCall(
            id=call.id,
            name=call.function.name,
            arguments=call.function.arguments or "{}",
        )
        for call in (message.tool_calls or [])
    )
    usage = getattr(response, "usage", None)
    turn = llm.LlmTurn(
        content=message.content or "",
        tool_calls=calls,
        model=str(getattr(response, "model", "") or ""),
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )
    return turn


# #############################################################################
# LiteLlmTokenCounter
# #############################################################################


class LiteLlmTokenCounter:
    """
    Implement ``operant.ports.llm.TokenCounter`` with litellm's tokenizers.
    """

    def __init__(self, model: str) -> None:
        self._model = model

    def count(self, messages: collections.abc.Sequence[llm.ChatMessage]) -> int:
        """
        Count the prompt tokens of ``messages`` for the configured model.
        """
        tokens = int(
            litellm.token_counter(
                model=self._model,
                messages=[_encode_message(m) for m in messages],
            )
        )
        return tokens

    def limit(self) -> Optional[int]:
        """
        Return the model's input limit from litellm's model map, if listed.
        """
        try:
            info = litellm.get_model_info(self._model)
            raw = info.get("max_input_tokens")
        # An unmapped model raises; the caller falls back to its budget.
        except Exception:
            raw = None
        limit = int(raw) if raw else None
        return limit


# Role -> Router model group; a missing group falls back to ``executor``.
ROLE_GROUPS: Final[Dict[str, str]] = {
    "executor": "executor",
    "planner": "planner",
    "verifier": "reviewer",
    "safety": "reviewer",
    "extract": "reviewer",
    "critic": "reviewer",
    "schema": "reviewer",
}


# #############################################################################
# ModelClients
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ModelClients:
    """
    One client per agent role, and the model each one resolves to.

    :ivar executor: The executor's client.
    :ivar roles: Clients for the other roles, by role name.
    :ivar models: The model id behind each role, executor included.
    """

    executor: LiteLlmClient
    roles: Dict[str, LiteLlmClient]
    models: Dict[str, str]


def load_router(path: pathlib.Path) -> litellm.Router:
    """
    Build a Router from a litellm router config file.

    The file holds ``model_list`` (deployments whose ``model_name`` is a
    role group) and optional ``router_settings``. Keys are read from the
    environment with ``os.environ/NAME``, never written in the file.

    :param path: The YAML file.
    :return: The Router.
    :raises errors.ConfigError: If the file is missing or malformed.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as err:
        raise errors.ConfigError(
            f"cannot read router config {path}: {err}"
        ) from err
    deployments = raw.get("model_list") if isinstance(raw, dict) else None
    if not deployments:
        raise errors.ConfigError(f"router config {path} has no model_list")
    groups = {d.get("model_name") for d in deployments}
    if "executor" not in groups:
        raise errors.ConfigError(
            f"router config {path} needs an 'executor' model group"
        )
    router = litellm.Router(
        model_list=deployments, **raw.get("router_settings", {})
    )
    return router


def _group_model(router: litellm.Router, group: str) -> str:
    """
    Return the model string of a Router group's first deployment.
    """
    model = next(
        str(d["litellm_params"]["model"])
        for d in router.model_list
        if d["model_name"] == group
    )
    return model


def build_clients(config: settings.DiscoverySettings) -> ModelClients:
    """
    Build the clients for every agent role.

    With ``router_config`` set, each role calls its Router model group
    (``executor``, ``planner``, ``reviewer``; missing groups fall back
    to ``executor``). Without it, the planner uses ``planner_model``,
    the reviewers ``verifier_model``, and both fall back to ``model``.

    :param config: The discovery settings group.
    :return: The clients and the model behind each role.
    """
    roles: Dict[str, LiteLlmClient] = {}
    models: Dict[str, str] = {}
    if config.router_config is not None:
        # One shared Router: per-role groups, timeouts, retries, fallbacks.
        router = load_router(config.router_config)
        groups = {d["model_name"] for d in router.model_list}
        for role, group in ROLE_GROUPS.items():
            alias = group if group in groups else "executor"
            roles[role] = LiteLlmClient(config, router=router, alias=alias)
            models[role] = _group_model(router, alias)
    else:
        # Plain settings: one model, with optional per-role overrides.
        overrides = {"planner": config.planner_model}
        for role, group in ROLE_GROUPS.items():
            model = (
                overrides.get(role)
                or (config.verifier_model if group == "reviewer" else None)
                or config.model
                or ""
            )
            roles[role] = LiteLlmClient(
                config.model_copy(update={"model": model})
            )
            models[role] = model
    executor = roles.pop("executor")
    clients = ModelClients(executor=executor, roles=roles, models=models)
    return clients
