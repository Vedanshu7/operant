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

    :ivar type:``text`` or ``image_url``.
    :ivar text: The text, for ``text`` parts.
    :ivar image_url: A ``data:`` or https URL, for ``image_url`` parts.
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

    :ivar id: Provider-assigned call id; echoed back on the tool reply.
    :ivar name: Function name from the tool schema.
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

    :ivar role: Who is speaking.
    :ivar content: Text, or content parts for a multimodal user turn.
    :ivar tool_calls: Calls an assistant turn made.
    :ivar tool_call_id: For ``tool`` role: the call this message
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

    :ivar name: Function name.
    :ivar description: What the function does, shown to the model.
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

    :ivar content: Assistant text, empty when the turn is tool calls
        only.
    :ivar tool_calls: Calls made this turn, in order.
    :ivar model: Model id that produced the turn, when reported.
    """

    content: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    model: str = ""
