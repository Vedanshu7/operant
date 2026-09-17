"""
The chat-completion port the discovery agent drives.

Import as:

import operant.ports.llm as plllm
"""

from __future__ import annotations

import collections.abc
from typing import Optional, Protocol, runtime_checkable

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

        :param messages: the conversation so far, system prompt first.
        :param tools: functions the model may call.
        :return: the assistant turn.
        """
        ...


# #############################################################################
# TokenCounter
# #############################################################################


@runtime_checkable
class TokenCounter(Protocol):
    """
    Count prompt tokens the way one model's tokenizer does.
    """

    def count(self, messages: collections.abc.Sequence[llm.ChatMessage]) -> int:
        """
        Count the tokens ``messages`` would cost as a prompt.

        :param messages: the messages of one call.
        :return: the token count.
        """
        ...

    def limit(self) -> Optional[int]:
        """
        Return the model's input-token limit, when known.

        :return: the limit, or ``None`` when the model is unknown.
        """
        ...
