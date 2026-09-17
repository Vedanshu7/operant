"""
Accessibility walker tests over a small fake element tree.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List, Optional, Sequence

import operant.adapters.macos.tools.observe as observe

# #############################################################################
# _Element
# #############################################################################


class _Element:
    """
    The parts of an ``xa11y`` element the walker reads.
    """

    def __init__(
        self,
        role: str,
        name: str = "",
        y: float = 0.0,
        kids: Sequence["_Element"] = (),
        raw: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.role = role
        self.name = name
        self.value = None
        self.description = ""
        self.enabled = True
        self.actions = ["press"]
        self.raw = raw or {}
        self.bounds = types.SimpleNamespace(x=10.0, y=y, width=100.0, height=20.0)
        self._kids = list(kids)

    def children(self) -> List["_Element"]:
        return self._kids


def _walk(root: _Element) -> observe._Walker:
    session = types.SimpleNamespace(app_name="App", refs={})
    walker = observe._Walker(session, (0.0, 0.0, 1000.0, 800.0))
    walker.walk(root, "content", 0)
    return walker


def _form() -> _Element:
    return _Element(
        "group",
        kids=[
            _Element("static_text", "Password", y=10),
            _Element("text_field", "Password", y=30),
            _Element(
                "button",
                "Log In",
                y=60,
                kids=[_Element("static_text", "Log In", y=62)],
            ),
        ],
    )


def test_text_anchors_only_the_next_control() -> None:
    controls = _walk(_form()).controls
    field, button = controls[0], controls[1]
    assert field.label == "Password"
    assert button.label == ""


def test_the_walk_reads_text_inside_a_control() -> None:
    assert _walk(_form()).texts.count("Log In") == 2
