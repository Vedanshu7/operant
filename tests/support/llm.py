"""
A scripted LLM for discovery tests - no litellm, no network.
"""

from __future__ import annotations

import collections.abc
import json
from typing import Any, Dict, List, Tuple

import operant.domain.models.llm as llm


def tool_turn(name: str, args: Dict[str, Any]) -> llm.LlmTurn:
    """
    Build a turn that makes exactly one tool call.
    """
    return llm.LlmTurn(
        tool_calls=(llm.ToolCall(id="t1", name=name, arguments=json.dumps(args)),)
    )


# #############################################################################
# ScriptedLlm
# #############################################################################


class ScriptedLlm:
    """
    Return queued turns in order; records every prompt it saw.
    """

    def __init__(self, turns: collections.abc.Sequence[llm.LlmTurn]) -> None:
        self._turns = list(turns)
        self.seen: List[List[llm.ChatMessage]] = []

    def complete(
        self,
        messages: collections.abc.Sequence[llm.ChatMessage],
        *,
        tools: collections.abc.Sequence[llm.ToolSchema],
    ) -> llm.LlmTurn:
        self.seen.append(list(messages))
        if not self._turns:
            return tool_turn("give_up", {"reason": "script exhausted"})
        return self._turns.pop(0)


def scripted(
    calls: collections.abc.Sequence[Tuple[str, Dict[str, Any]]],
) -> ScriptedLlm:
    """
    Build a scripted LLM from ``(tool name, args)`` pairs.
    """
    return ScriptedLlm([tool_turn(name, args) for name, args in calls])
