"""
Discovery opens agent memory only for the runs its mode covers.
"""

from __future__ import annotations

import pathlib
from typing import Literal

import pytest

import operant.application.usecases.discover as discover
import tests.support.settings as tssettin


@pytest.mark.parametrize(
    ("mode", "agents", "opened"),
    [
        ("all", "single", True),
        ("all", "multi", True),
        ("multi", "single", False),
        ("multi", "multi", True),
        ("off", "multi", False),
    ],
)
def test_memory_follows_its_mode(
    tmp_path: pathlib.Path,
    mode: Literal["all", "multi", "off"],
    agents: str,
    opened: bool,
) -> None:
    settings = tssettin.test_settings(tmp_path)
    settings.discovery.memory = mode
    assert (discover._memory(settings, agents) is not None) is opened
