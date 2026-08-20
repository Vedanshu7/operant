"""
The evidence sink port: a run's redacted event log and screenshots.

Every write is redacted first, never after. A screenshot that produced
no image is a logged ``screenshot_failed`` event, not a silent gap.

Import as:

import operant.ports.evidence as evidence
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import operant.domain.events as events
import operant.ports.surface as surface

if TYPE_CHECKING:
    import operant.domain.redaction as redact


# #############################################################################
# EvidenceSink
# #############################################################################


@runtime_checkable
class EvidenceSink(Protocol):
    """
    Where a run's events and screenshots go.

    :ivar run_id: Id of the run being logged.
    :ivar dir: Directory the log and screenshots are written to.
    :ivar redactor: Redacts secrets from everything before it is
        written.
    """

    run_id: str
    dir: pathlib.Path
    redactor: redact.Redactor

    def emit(self, event: events.BaseEvent) -> None:
        """
        Append one typed event, redacted, with ``seq`` and ``at``.
        """
        ...

    def event(self, type_: str, **data: Any) -> None:
        """
        Validate ``data`` against the event registry and emits it.

        :param type_: Event type name. :param **data: Event fields;
            ``type``, ``seq``, and ``at`` are reserved.
        :raises ValueError: If ``type_`` is unknown or a reserved field
            was passed.
        """
        ...

    def screenshot(self, target: surface.Surface, label: str) -> str:
        """
        Capture the surface to a numbered file in ``dir``.

        :param target: Surface to capture.
        :param label: What the image shows; becomes part of the name.
        :return: The saved file name, or ``""`` when no image was
            produced (the failure is itself an event).
        """
        ...
