"""Structured evidence for a run: a JSONL event log plus screenshots.

Everything lands under ``<evidence_root>/<run_id>/``. Every write is
redacted first, never after. Events are typed (``operant.domain.events``)
and validated before they hit disk. A screenshot that produced no image is
a logged ``screenshot_failed`` event, not a silent gap - an agent that
believes it can see must not run blind unnoticed.

Typical usage example:

  log = RunLog(settings.paths.evidence_dir, run_id, redactor)
  log.emit(events.ReplayStarted(...))
  shot = log.screenshot(surface, "failure-edge-3")

Import as:

import operant.infra.evidence.run_log as run_log
"""

from __future__ import annotations

import collections.abc
import json
import logging
import pathlib
from typing import Any, Dict, Final, FrozenSet, List

import operant.domain.events as events
import operant.domain.models.graph as graph
import operant.domain.redaction as redact
import operant.helpers.logging as hlloggin
import operant.helpers.text as text
import operant.helpers.time as time
import operant.ports.surface as surface

_RESERVED: Final[FrozenSet[str]] = frozenset({"type", "seq", "at"})
LOG_FILE_NAME: Final = "run-log.jsonl"

Listener = collections.abc.Callable[[dict[str, Any]], None]

_LOG = hlloggin.get_logger(__name__)


# #############################################################################
# RunLog
# #############################################################################


class RunLog:
    """
    Implements ``operant.ports.evidence.EvidenceSink`` on disk.

    :ivar run_id: The run being logged.
    :ivar dir: Directory holding the log and screenshots.
    :ivar redactor: Applied to every entry before it is written.
    :ivar listeners: Called with each redacted entry after it is
        written; the server uses this to stream events live.
    """

    def __init__(
        self,
        evidence_root: pathlib.Path,
        run_id: str,
        redactor: redact.Redactor,
        *,
        echo: bool = True,
    ) -> None:
        self.run_id = run_id
        self.dir = evidence_root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.redactor = redactor
        self.listeners: List[Listener] = []
        self._log_path = self.dir / LOG_FILE_NAME
        self._seq = 0
        self._shots = 0
        self._echo = echo
        self.emit(
            events.RunMeta(run_id=run_id, schema_version=graph.SCHEMA_VERSION)
        )

    @property
    def seq(self) -> int:
        """
        Sequence number the next event will receive.
        """
        return self._seq

    def emit(self, event: events.BaseEvent) -> None:
        """
        Append one typed event, redacted, stamped with ``seq``/``at``.
        """
        payload = event.model_dump(by_alias=True, exclude={"seq", "at"})
        entry = self.redactor.redact_deep(
            {"seq": self._seq, "at": time.iso_now(), **payload}
        )
        self._seq += 1
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        if self._echo and event.summary:
            _LOG.info(
                "[%s] %s", event.type, self.redactor.redact(str(event.summary))
            )
        for listener in list(self.listeners):
            listener(entry)

    def event(self, type_: str, **data: Any) -> None:
        """
        Validate ``data`` against the event registry and emits it.

        :raises ValueError: If ``type_`` is unknown or a reserved field
            was passed - a stray ``type=`` kwarg once destroyed the
            event name of every ``input_declared`` entry.
        """
        reserved = _RESERVED & data.keys()
        if reserved:
            raise ValueError(
                f"reserved event field(s) {sorted(reserved)} in {type_!r}"
            )
        model = events.EVENT_REGISTRY.get(type_)
        if model is None:
            raise ValueError(f"unknown event type {type_!r}")
        self.emit(model.model_validate({"type": type_, **data}))

    def screenshot(self, target: surface.Surface, label: str) -> str:
        """
        Capture ``target`` to ``NNN-<label>.png``; ``""`` on failure.
        """
        safe = text.safe_filename(label)
        name = f"{self._shots:03d}-{safe}.png"
        self._shots += 1
        path = self.dir / name
        result = ""
        try:
            ok = target.screenshot(path)
        except Exception as err:
            self._screenshot_failed(label, str(err))
        else:
            if ok and path.exists() and path.stat().st_size > 0:
                # A real image landed on disk: record it as saved.
                self.emit(events.ScreenshotSaved(file=name, label=label))
                result = name
            else:
                # No image produced: log the failure, return "".
                self._screenshot_failed(label, "surface produced no image")
        return result

    def _screenshot_failed(self, label: str, error: str) -> None:
        """
        Emit a ``screenshot_failed`` event for ``label``.
        """
        self.emit(
            events.ScreenshotFailed(
                label=label,
                error=error,
                summary=f"screenshot {label!r} FAILED: {error}",
            )
        )


def read_entries(log_path: pathlib.Path) -> List[Dict[str, Any]]:
    """
    Load every entry of a run log as dictionaries.

    :param log_path: The ``run-log.jsonl`` file.
    :return: Entries in file order; malformed lines are skipped with a
        warning.
    """
    entries: List[Dict[str, Any]] = []
    with log_path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                _LOG.warning("%s:%d: malformed entry skipped", log_path, number)
    return entries


def quiet(level: int = logging.WARNING) -> None:
    """
    Lower the echo verbosity (used by tests and the server).
    """
    _LOG.setLevel(level)
