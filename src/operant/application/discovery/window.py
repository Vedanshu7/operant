"""
The prompt window: what of the discovery history is sent to the model.

The stored history keeps every turn as the record; this module decides
what each call actually carries. Only the newest screenshot is attached,
only the last few screen digests are sent in full, and the whole window
must fit a token budget derived from the model's input limit. Message
order and every tool call/reply pair are preserved, so the request stays
valid for the provider.

Import as:

import operant.application.discovery.window as dswindow
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import List, Optional, Tuple

import operant.domain.models.llm as llm
import operant.ports.llm as plllm

# Rough sizes for the fallback estimator, used when no tokenizer is wired.
_CHARS_PER_TOKEN = 4
_IMAGE_TOKENS = 1600
_SCREEN_MARK = "Current screen:\n"


# #############################################################################
# WindowBudget
# #############################################################################


@dataclasses.dataclass(frozen=True)
class WindowBudget:
    """
    How much history a model call may carry.

    :ivar keep_full_turns: Newest turns whose screen digest is sent in
        full; older turns keep only their window title.
    :ivar budget_ratio: Share of the model's input limit the window may
        use, leaving room for the reply and estimation error.
    :ivar max_tokens: The budget when the model's input limit is
        unknown.
    """

    keep_full_turns: int = 3
    budget_ratio: float = 0.6
    max_tokens: int = 100_000


# #############################################################################
# EstimatedCounter
# #############################################################################


class EstimatedCounter:
    """
    Estimate tokens from text length when no model tokenizer is wired.
    """

    def count(self, messages: collections.abc.Sequence[llm.ChatMessage]) -> int:
        """
        Estimate the tokens ``messages`` would cost.
        """
        chars, images = 0, 0
        for message in messages:
            if isinstance(message.content, str):
                chars += len(message.content)
            else:
                for part in message.content:
                    chars += len(part.text)
                    images += 1 if part.type == "image_url" else 0
            chars += sum(len(call.arguments) for call in message.tool_calls)
        estimate = chars // _CHARS_PER_TOKEN + images * _IMAGE_TOKENS
        return estimate

    def limit(self) -> Optional[int]:
        """
        Report no known input limit.
        """
        return None


# #############################################################################
# Window
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Window:
    """
    One model call's messages, and what was left out to fit.

    :ivar messages: The system turn followed by the windowed history.
    :ivar tokens: Counted (or estimated) tokens of ``messages``.
    :ivar limit: The token budget the window had to fit.
    :ivar kept_full: Turns sent with their full screen digest.
    :ivar dropped_images: Older screenshots replaced by a note.
    """

    messages: Tuple[llm.ChatMessage, ...]
    tokens: int
    limit: int
    kept_full: int
    dropped_images: int


def build(
    system: str,
    history: collections.abc.Sequence[llm.ChatMessage],
    *,
    budget: WindowBudget,
    counter: plllm.TokenCounter,
) -> Window:
    """
    Build the window for one call, compacting harder until it fits.

    The caller checks ``tokens <= limit``; a window that still does not
    fit with one full turn is returned as-is so the caller can fail the
    run with the numbers instead of silently cutting the goal.

    :param system: The system prompt.
    :param history: The stored conversation, oldest first.
    :param budget: The window budget.
    :param counter: Counts tokens for the model in use.
    :return: The smallest window the rules allow, or the first that
        fits.
    """
    model_limit = counter.limit()
    limit = (
        int(model_limit * budget.budget_ratio)
        if model_limit
        else budget.max_tokens
    )
    keep = max(1, budget.keep_full_turns)
    window = _render(system, history, keep, counter, limit)
    while window.tokens > limit and keep > 1:
        # Over budget: send one fewer full digest and count again.
        keep -= 1
        window = _render(system, history, keep, counter, limit)
    return window


def _render(
    system: str,
    history: collections.abc.Sequence[llm.ChatMessage],
    keep: int,
    counter: plllm.TokenCounter,
    limit: int,
) -> Window:
    """
    Render the history keeping ``keep`` full digests and one screenshot.
    """
    screen_turns = [
        i
        for i, message in enumerate(history)
        if message.role == "user" and not isinstance(message.content, str)
    ]
    newest = len(screen_turns) - 1
    age = {index: newest - n for n, index in enumerate(screen_turns)}
    out: List[llm.ChatMessage] = [llm.ChatMessage(role="system", content=system)]
    dropped = 0
    for index, message in enumerate(history):
        if index in age:
            # A screen turn: compact it by age.
            compacted, lost = _compact(message, age[index], keep, index)
            out.append(compacted)
            dropped += lost
        else:
            # Assistant calls and tool replies always pass through.
            out.append(message)
    window = Window(
        messages=tuple(out),
        tokens=counter.count(out),
        limit=limit,
        kept_full=min(keep, len(screen_turns)),
        dropped_images=dropped,
    )
    return window


def _compact(
    message: llm.ChatMessage, age: int, keep: int, index: int
) -> Tuple[llm.ChatMessage, int]:
    """
    Compact one screen turn: drop old screenshots and old digests.
    """
    original = () if isinstance(message.content, str) else message.content
    parts: List[llm.ContentPart] = []
    dropped = 0
    for part in original:
        if part.type == "image_url" and age > 0:
            # Only the newest screenshot is worth its tokens.
            parts.append(
                llm.ContentPart(
                    type="text", text=f"[screenshot from message {index} omitted]"
                )
            )
            dropped += 1
        elif part.type == "text" and age >= keep:
            # An old digest: keep where the agent was, not every control.
            parts.append(
                llm.ContentPart(type="text", text=_title_only(part.text))
            )
        else:
            # Recent enough to send unchanged.
            parts.append(part)
    compacted = dataclasses.replace(message, content=tuple(parts))
    return compacted, dropped


def _title_only(text: str) -> str:
    """
    Reduce a turn's text to the window line of its screen digest.
    """
    _, mark, screen = text.partition(_SCREEN_MARK)
    first = screen.splitlines()[0] if mark and screen else "(no window)"
    reduced = f"[earlier turn] {first} - full screen digest omitted"
    return reduced
