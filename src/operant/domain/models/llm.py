"""
Provider-neutral chat completion shapes.

The discovery agent talks to the model through ``operant.ports.llm``;
these are the messages it sends and the turn it gets back. They mirror
the OpenAI-style tool-calling contract litellm normalises every provider
to: an assistant turn carries zero or more tool calls, each with an id,
a function name, and a JSON-encoded argument string.

Import as:

import operant.domain.models.llm as llm
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Literal, Optional, Tuple, Union

Role = Literal["system", "user", "assistant", "tool"]


# #############################################################################
# ContentPart
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ContentPart:
    """
    One block of a multimodal user message.

    :ivar type: ``text`` or ``image_url``.
    :ivar text: the text, for ``text`` parts.
    :ivar image_url: a ``data:`` or https URL, for ``image_url`` parts.
    """

    type: Literal["text", "image_url"]
    text: str = ""
    image_url: str = ""


# #############################################################################
# ToolCall
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ToolCall:
    """
    A function call the model asked for.

    :ivar id: provider-assigned call id; echoed back on the tool reply.
    :ivar name: function name from the tool schema.
    :ivar arguments: JSON-encoded arguments exactly as the model wrote
        them; the caller parses and validates.
    """

    id: str
    name: str
    arguments: str


# #############################################################################
# ChatMessage
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ChatMessage:
    """
    One message in the conversation.

    :ivar role: who is speaking.
    :ivar content: text, or content parts for a multimodal user turn.
    :ivar tool_calls: calls an assistant turn made.
    :ivar tool_call_id: for ``tool`` role: the call this message
        answers.
    """

    role: Role
    content: Union[str, Tuple[ContentPart, ...]] = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    tool_call_id: Optional[str] = None


# #############################################################################
# ToolSchema
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ToolSchema:
    """
    A function the model may call.

    :ivar name: function name.
    :ivar description: what the function does, shown to the model.
    :ivar parameters: JSON Schema of the arguments object.
    """

    name: str
    description: str
    parameters: Dict[str, Any]


# #############################################################################
# LlmTurn
# #############################################################################


@dataclasses.dataclass(frozen=True)
class LlmTurn:
    """
    What the model answered.

    :ivar content: assistant text, empty when the turn is tool calls
        only.
    :ivar tool_calls: calls made this turn, in order.
    :ivar model: model id that produced the turn, when reported.
    :ivar input_tokens: prompt tokens billed for the turn, when
        reported.
    :ivar output_tokens: completion tokens billed for the turn, when
        reported.
    """

    content: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


# #############################################################################
# TraceContext
# #############################################################################


@dataclasses.dataclass(frozen=True)
class TraceContext:
    """
    Where one model call belongs in the observability backend.

    :ivar trace_id: 32 lowercase hex chars; one trace per run.
    :ivar session_id: groups traces, e.g. the run id or an eval session.
    :ivar trace_name: human-readable trace name.
    :ivar generation_name: this call's name, e.g. ``executor-turn-3``.
    :ivar agent: the role that made the call.
    :ivar tags: free-form labels (vendor, tenant, eval scenario...).
    """

    trace_id: str
    session_id: str
    trace_name: str
    generation_name: str
    agent: str = "executor"
    tags: Tuple[str, ...] = ()
