"""
Litellm-backed chat completion.

Multi-provider: ``anthropic/...``, ``openai/...``, or any OpenAI-
compatible endpoint via the configured api base. The model string, base
URL, and key come from settings - never from the environment directly.
Retrying lives in the discovery loop, which logs each failed attempt as
evidence; this client maps one failure to one ``LlmError``.

Import as:

import operant.adapters.llm.litellm_client as litecli
"""

from __future__ import annotations

import collections.abc
from typing import Any, Dict

import litellm

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

    def __init__(self, config: settings.DiscoverySettings) -> None:
        if not config.model:
            raise errors.ConfigError(
                "no discovery model configured "
                "(set OPERANT_DISCOVERY__MODEL or LLM_MODEL)"
            )
        self._model = config.model
        self._api_base = config.api_base
        self._api_key = (
            config.api_key.get_secret_value() if config.api_key else None
        )

    def complete(
        self,
        messages: collections.abc.Sequence[llm.ChatMessage],
        *,
        tools: collections.abc.Sequence[llm.ToolSchema],
    ) -> llm.LlmTurn:
        """
        Run one completion with tool calling required.
        """
        try:
            response = litellm.completion(
                model=self._model,
                messages=[_encode_message(m) for m in messages],
                tools=[_encode_tool(t) for t in tools],
                tool_choice="required",
                api_base=self._api_base,
                api_key=self._api_key,
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
    turn = llm.LlmTurn(
        content=message.content or "",
        tool_calls=calls,
        model=str(getattr(response, "model", "") or ""),
    )
    return turn
