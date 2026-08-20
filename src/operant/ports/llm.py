"""
The chat-completion port the discovery agent drives.

Import as:

import operant.ports.llm as plllm
"""

from __future__ import annotations

import collections.abc
from typing import Protocol, runtime_checkable

import operant.domain.models.llm as llm

# #############################################################################
# LlmClient
# #############################################################################


@runtime_checkable
class LlmClient(Protocol):
    """
    One model behind a provider-neutral tool-calling interface.
    """

    def complete(
        self,
        messages: collections.abc.Sequence[llm.ChatMessage],
        *,
        tools: collections.abc.Sequence[llm.ToolSchema],
    ) -> llm.LlmTurn:
        """
        Run one completion with tool calling required.

        :param messages: The conversation so far, system prompt first.
        :param tools: Functions the model may call.
        :return: The assistant turn.
        """
        ...
