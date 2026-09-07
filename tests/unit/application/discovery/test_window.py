"""
Prompt-window tests: old screenshots and digests are compacted, tool call/reply
pairs survive, and the token budget is enforced.
"""

from __future__ import annotations

import collections.abc
import pathlib
from typing import List

import operant.adapters.secrets.env as env
import operant.application.discovery.prompt as prompt
import operant.application.discovery.window as dswindow
import operant.domain.models.llm as llm
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes
import tests.support.llm as sllm


def _turn(n: int) -> List[llm.ChatMessage]:
    screen = llm.ChatMessage(
        role="user",
        content=(
            llm.ContentPart(
                type="text",
                text=f"GOAL: g\n\nCurrent screen:\nWINDOW: Page {n}\nCONTROLS (9):",
            ),
            llm.ContentPart(
                type="image_url", image_url="data:image/png;base64,AA"
            ),
        ),
    )
    call = llm.ChatMessage(
        role="assistant",
        tool_calls=(llm.ToolCall(id=f"t{n}", name="act", arguments="{}"),),
    )
    reply = llm.ChatMessage(role="tool", content="OK", tool_call_id=f"t{n}")
    return [screen, call, reply]


def _history(turns: int) -> List[llm.ChatMessage]:
    return [m for n in range(1, turns + 1) for m in _turn(n)]


def _texts(message: llm.ChatMessage) -> List[str]:
    assert not isinstance(message.content, str)
    return [part.text for part in message.content]


# #############################################################################
# _FixedCounter
# #############################################################################


class _FixedCounter:
    """
    Charge a fixed cost per full digest, so the budget is predictable.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit

    def count(self, messages: collections.abc.Sequence[llm.ChatMessage]) -> int:
        full = sum(
            1
            for m in messages
            if not isinstance(m.content, str)
            and any("CONTROLS" in p.text for p in m.content)
        )
        return full * 100

    def limit(self) -> int:
        return self._limit


def _system_tokens() -> int:
    system = prompt.build_system_prompt([], "Google Chrome")
    return dswindow.EstimatedCounter().count(
        [llm.ChatMessage(role="system", content=system)]
    )


def test_only_the_newest_screenshot_is_sent() -> None:
    window = dswindow.build(
        "sys",
        _history(3),
        budget=dswindow.WindowBudget(),
        counter=dswindow.EstimatedCounter(),
    )
    images = [
        part
        for m in window.messages
        if not isinstance(m.content, str)
        for part in m.content
        if part.type == "image_url"
    ]
    assert len(images) == 1
    assert window.dropped_images == 2


def test_old_digests_keep_only_their_window_line() -> None:
    window = dswindow.build(
        "sys",
        _history(4),
        budget=dswindow.WindowBudget(keep_full_turns=2),
        counter=dswindow.EstimatedCounter(),
    )
    screens = [m for m in window.messages if m.role == "user"]
    assert _texts(screens[0])[0] == (
        "[earlier turn] WINDOW: Page 1 - full screen digest omitted"
    )
    assert "CONTROLS" in _texts(screens[-1])[0]
    assert "CONTROLS" in _texts(screens[-2])[0]


def test_tool_calls_keep_their_replies_in_order() -> None:
    history = _history(5)
    window = dswindow.build(
        "sys",
        history,
        budget=dswindow.WindowBudget(keep_full_turns=1),
        counter=dswindow.EstimatedCounter(),
    )
    sent = window.messages[1:]
    assert [m.role for m in sent] == [m.role for m in history]
    for message, original in zip(sent, history):
        if message.role != "user":
            assert message == original


def test_budget_drops_full_digests_until_it_fits() -> None:
    window = dswindow.build(
        "sys",
        _history(4),
        budget=dswindow.WindowBudget(keep_full_turns=3, budget_ratio=1.0),
        counter=_FixedCounter(limit=150),
    )
    assert window.kept_full == 1
    assert window.tokens <= window.limit


def test_an_unfittable_window_fails_the_run(tmp_path: pathlib.Path) -> None:
    scenario = next(
        s
        for s in catalog.FAMILIES["auth"](scenes.SKINS[0])
        if s.name == "already_logged_in"
    )
    run = harness.run_scenario(
        tmp_path,
        sllm.scripted([]),
        env.EnvSecretStore({}),
        scenario,
        window_budget=dswindow.WindowBudget(max_tokens=10),
    )
    assert getattr(run.result, "failure_class", "") == "context_exhausted"
    assert run.llm.turns == []


def test_forced_compaction_is_logged(tmp_path: pathlib.Path) -> None:
    scenario = next(s for s in catalog.FAMILIES["context"](scenes.SKINS[0]))
    calls = [("act", {"action": "click", "ref": "next", "intent": "next"})] * 6
    run = harness.run_scenario(
        tmp_path,
        sllm.scripted(calls),
        env.EnvSecretStore({}),
        scenario,
        # Room for the system prompt plus about one full screen turn.
        window_budget=dswindow.WindowBudget(
            keep_full_turns=3, max_tokens=_system_tokens() + 400
        ),
    )
    compacted = [e for e in run.events() if e.get("type") == "context_compacted"]
    assert compacted
    assert run.surface.visited[-1] == "p7"
