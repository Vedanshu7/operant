"""
The tool port: the platform's extension point.

A tool serves one or more action kinds and is chained by the gateway per
action kind. See ``operant.domain.models.tools`` for the value types.

Import as:

import operant.ports.tool as pttool
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import operant.domain.models.actions as actions
import operant.domain.models.tools as tools

# #############################################################################
# Tool
# #############################################################################


@runtime_checkable
class Tool(Protocol):
    """
    One actuator or observer the gateway can dispatch to.

    :ivar spec: What the tool is and which action kinds it serves.
    """

    spec: tools.ToolSpec

    def health(self) -> tools.ToolHealth:
        """
        Report whether the tool can act right now.
        """
        ...

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Perform ``action`` with the session and target in ``ctx``.

        :param action: The resolved action.
        :param ctx: Session, last digest, and resolved target handle.
        :return: The outcome; ``unsupported`` lets the chain fall
            through.
        """
        ...
