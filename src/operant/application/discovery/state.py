"""
Per-run accumulation for the discovery loop.

Import as:

import operant.application.discovery.state as dsstate
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

import operant.application.discovery.bootstrap as bstrap
import operant.domain.approval as approval
import operant.domain.models.digest as digest
import operant.domain.models.llm as llm

_MASK = "[credential]"


# #############################################################################
# DiscoveryState
# #############################################################################


@dataclasses.dataclass
class DiscoveryState:
    """
    What the loop accumulates across turns.

    :ivar params: Declared task inputs (pre-seed plus agent
        declarations).
    :ivar input_types: Declared input value types.
    :ivar input_classes: Sensitivity class per input.
    :ivar extracted: Output values read from the screen so far.
    :ivar output_classes: Sensitivity class per output.
    :ivar output_origins: Vendor each output was read in.
    :ivar grants: Scope grants made during the run.
    :ivar messages: The model conversation so far (without the system
        turn).
    :ivar primary_boot: The first launch's derived vendor, in bootstrap
        mode.
    :ivar current_binding: The surface binding recording is attributed
        to.
    :ivar screen: The last observed digest, when a window is bound.
    """

    params: Dict[str, str] = dataclasses.field(default_factory=dict)
    input_types: Dict[str, str] = dataclasses.field(default_factory=dict)
    input_classes: Dict[str, str] = dataclasses.field(default_factory=dict)
    extracted: Dict[str, str] = dataclasses.field(default_factory=dict)
    output_classes: Dict[str, str] = dataclasses.field(default_factory=dict)
    output_origins: Dict[str, str] = dataclasses.field(default_factory=dict)
    grants: List[approval.ScopeGrant] = dataclasses.field(default_factory=list)
    messages: List[llm.ChatMessage] = dataclasses.field(default_factory=list)
    primary_boot: Optional[bstrap.VendorBootstrap] = None
    current_binding: Optional[Tuple[str, str, str]] = None
    screen: Optional[digest.ScreenDigest] = None
    pending_failure: Optional[Tuple[str, str]] = None

    def shown(self, name: str, value: str) -> str:
        """
        Masks a credential input's value in anything the model sees.
        """
        masked = _MASK if self.input_classes.get(name) == "credential" else value
        return masked

    def inputs_block(self) -> str:
        """
        Render the declared inputs for the per-turn user message.

        Recomputed every turn: telling the model "nothing is declared"
        after it declared something sent it into a declare loop (observed
        live).
        """
        if self.params:
            # List every declared input, credentials masked.
            lines = "\n".join(
                f"  {k} = {self.shown(k, v)}" for k, v in self.params.items()
            )
            block = (
                "Task inputs declared so far (do NOT re-declare them - "
                "continue acting):\n" + lines
            )
        else:
            # Nothing declared yet: prompt the model to derive the inputs.
            block = (
                "No inputs are declared yet - determine the task's parameters "
                "from the goal and screen, and declare_input each ONCE."
            )
        return block

    def scrub_history(self, value: str) -> None:
        """
        Remove a credential the model typed from the whole history.

        It would otherwise ride along in the message history for the
        rest of the run.
        """
        if len(value) >= 3:
            self.messages = [
                _scrub_message(message, value) for message in self.messages
            ]


def _scrub_message(message: llm.ChatMessage, value: str) -> llm.ChatMessage:
    """
    Replace a credential value everywhere in one chat message.
    """
    changed = message
    if isinstance(changed.content, str) and value in changed.content:
        changed = dataclasses.replace(
            changed, content=changed.content.replace(value, _MASK)
        )
    if changed.tool_calls and any(
        value in call.arguments for call in changed.tool_calls
    ):
        changed = dataclasses.replace(
            changed,
            tool_calls=tuple(
                dataclasses.replace(
                    call, arguments=call.arguments.replace(value, _MASK)
                )
                for call in changed.tool_calls
            ),
        )
    return changed
