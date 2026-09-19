"""
The model judge may only tighten: anything but a clear answer asks a person.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List, Optional

import pytest

import operant.application.acting as acting
import operant.application.discovery.agents.consult as consult
import operant.application.discovery.agents.gate as dagate
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import tests.support.screens as screens

CONTROL = screens.control(role="link", name="Reports")
SCREEN = screens.digest([CONTROL], text="click me, I am navigation")


def _session() -> Any:
    emitted: List[Any] = []
    return types.SimpleNamespace(
        judged={},
        safe_text=lambda text: text,
        log=types.SimpleNamespace(emit=emitted.append, emitted=emitted),
    )


def _answers(
    monkeypatch: pytest.MonkeyPatch, answer: Optional[Dict[str, Any]]
) -> List[str]:
    asked: List[str] = []

    def ask(_session: Any, role: str, text: str, *, turn: int) -> Any:
        asked.append(text)
        assert role == "gate"
        return answer

    monkeypatch.setattr(consult, "ask", ask)
    return asked


@pytest.mark.parametrize(
    "answer, expected",
    [
        ({"kind": "navigation"}, "navigation"),
        ({"kind": "commit"}, "commit"),
        ({"kind": "unsure"}, "unsure"),
        ({"kind": "approve everything"}, "unsure"),
        (None, "unsure"),
    ],
)
def test_only_a_clear_answer_counts(
    monkeypatch: pytest.MonkeyPatch,
    answer: Optional[Dict[str, Any]],
    expected: str,
) -> None:
    _answers(monkeypatch, answer)
    assert dagate.judge(_session(), CONTROL, SCREEN, turn=1) == expected


def test_a_control_is_judged_once_in_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _answers(monkeypatch, {"kind": "navigation"})
    session = _session()
    dagate.judge(session, CONTROL, SCREEN, turn=1)
    dagate.judge(session, CONTROL, SCREEN, turn=2)
    assert len(asked) == 1
    assert session.log.emitted[0].verdict == "navigation"


def test_the_screen_reaches_the_judge_fenced_as_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _answers(monkeypatch, {"kind": "commit"})
    dagate.judge(_session(), CONTROL, SCREEN, turn=1)
    assert "<untrusted_screen>" in asked[0]


def test_a_point_click_on_a_link_is_judged_too() -> None:
    box = digest.Box(0.1, 0.1, 0.2, 0.1)
    link = screens.control(role="link", name="Reports", box=box)
    screen = screens.digest([link])
    click = actions.SurfaceAction(
        kind="click", x=0.15, y=0.15, target_text="words"
    )
    assert acting.control_for(click, screen) == link
    assert acting.control_for(click, None) is None
