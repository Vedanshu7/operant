import json
import pathlib
from typing import Dict, List

import pytest

import operant.domain.events as events
import operant.domain.redaction as redact
import operant.infra.evidence.run_log as run_log
import operant.ports.evidence as evidence
import tests.support.ports as ports

# #############################################################################
# ShootingSurface
# #############################################################################


class ShootingSurface(ports.FakeSurface):

    def __init__(self) -> None:
        super().__init__()
        self.ok = True

    def screenshot(self, path: pathlib.Path) -> bool:
        if self.ok:
            path.write_bytes(b"\x89PNG fake")
        return self.ok


def _log(tmp_path: pathlib.Path) -> run_log.RunLog:
    redactor = redact.Redactor()
    redactor.add_secret("hunter2-pw")
    return run_log.RunLog(tmp_path, "replay-test", redactor, echo=False)


def test_first_entry_is_run_meta_and_entries_are_redacted(
    tmp_path: pathlib.Path,
) -> None:
    log = _log(tmp_path)
    assert isinstance(log, evidence.EvidenceSink)
    log.emit(
        events.InputDeclared(
            name="password",
            value="hunter2-pw",
            summary="declared password=hunter2-pw",
        )
    )
    entries = run_log.read_entries(tmp_path / "replay-test" / "run-log.jsonl")
    assert entries[0]["type"] == "run_meta" and entries[0]["seq"] == 0
    assert entries[1]["seq"] == 1 and "hunter2" not in json.dumps(entries[1])
    assert entries[1]["value"] == "[REDACTED]"
    assert log.seq == 2


def test_reserved_and_unknown_event_fields_are_rejected(
    tmp_path: pathlib.Path,
) -> None:
    log = _log(tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        log.event("replay_started", seq=5, summary="x")
    with pytest.raises(ValueError, match="unknown event type"):
        log.event("not_an_event", summary="x")


def test_screenshot_success_and_failure_are_both_events(
    tmp_path: pathlib.Path,
) -> None:
    log = _log(tmp_path)
    seen: List[Dict[str, object]] = []
    log.listeners.append(seen.append)
    surface = ShootingSurface()
    name = log.screenshot(surface, "failure edge-3/2")
    assert name == "000-failure-edge-3-2.png"
    assert (tmp_path / "replay-test" / name).stat().st_size > 0
    surface.ok = False
    assert log.screenshot(surface, "blind") == ""
    assert [entry["type"] for entry in seen] == [
        "screenshot_saved",
        "screenshot_failed",
    ]
