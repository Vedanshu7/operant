"""
The tool contract's value types: spec, health, result, context.

A tool serves one or more action kinds. Integrating a new capability (a
CDP driver, an OCR observer, a Windows UIA actuator) means implementing
``operant.ports.tool.Tool`` with these types and adding the tool's name
to a chain in the gateway policy; no engine or dispatcher changes.

Import as:

import operant.domain.models.tools as tools
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, FrozenSet, Literal, Optional, Tuple

import operant.domain.models.digest as mddigest

ActionKind = Literal[
    "observe", "launch", "click", "fill", "press", "select", "scroll"
]


# #############################################################################
# ToolSpec
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    """
    What a tool is and what it serves.

    :ivar name: Unique tool name referenced by gateway chains.
    :ivar version: Tool version string.
    :ivar serves: Action kinds the tool can execute.
    :ivar platform: OS the tool runs on.
    :ivar permissions: Human-readable requirements (e.g. Accessibility).
    :ivar leaks_value: Whether the typed value leaves the process
        (pasteboard, argv). Such a tool is never used for a sensitive
        fill, whatever the chain order says.
    """

    name: str
    version: str
    serves: FrozenSet[str]
    platform: str = "darwin"
    permissions: Tuple[str, ...] = ()
    leaks_value: bool = False


# #############################################################################
# ToolHealth
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ToolHealth:
    """
    Whether a tool can currently act.

    :ivar status:``ok``, ``degraded``, or ``unavailable``.
    :ivar reason: Why the status is not ``ok``.
    """

    status: Literal["ok", "degraded", "unavailable"]
    reason: str = ""


# #############################################################################
# ToolResult
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ToolResult:
    """
    The outcome of one tool execution.

    :ivar status:``ok``, ``failed``, or ``unsupported``.
    :ivar reason: Why the status is not ``ok``.
    :ivar verified: True when the tool itself confirmed the effect (e.g.
        the value settled). Unverified ``ok`` results are checked by the
        dispatcher's shared verifier.
    :ivar digest: The observation, for observer tools.
    """

    status: Literal["ok", "failed", "unsupported"]
    reason: str = ""
    verified: bool = False
    digest: Optional[mddigest.ScreenDigest] = None


# #############################################################################
# Attempt
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Attempt:
    """
    One tool's outcome for one dispatched action.

    :ivar tool: Name of the tool that was tried.
    :ivar status:``ok``, ``failed``, ``unsupported``,
        ``skipped_unavailable``, or ``skipped_sensitive``.
    :ivar reason: Why the status is not ``ok``.
    """

    tool: str
    status: str
    reason: str = ""


# #############################################################################
# ExecutionContext
# #############################################################################


@dataclasses.dataclass
class ExecutionContext:
    """
    Everything a tool may need to act.

    Tools never resolve targets; resolution stays a pure function
    outside the gateway.

    :ivar session: The window session; opaque to the core, typed by
        tools.
    :ivar digest: The last observation, when one exists.
    :ivar target: Resolved element handle for click/fill.
    :ivar extras: Tool-specific extras.
    """

    session: Any
    digest: Optional[mddigest.ScreenDigest] = None
    target: Any = None
    extras: Dict[str, Any] = dataclasses.field(default_factory=dict)
