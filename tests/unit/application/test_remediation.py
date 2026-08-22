"""
Remediation memory: error normalization, record/query, reinforcement.
"""

import pathlib

import operant.application.remediation as remem
import operant.domain.remediation as odremed
import operant.infra.repositories.remediations as store


def test_error_signature_strips_volatile_parts() -> None:
    a = odremed.error_signature("stale ref c12 at 0x7ffe (observe again)")
    b = odremed.error_signature("stale ref c99 at 0x0011 (observe again)")
    assert a == b
    assert "c#" in a and "12" not in a


def test_error_signature_strips_quoted_values() -> None:
    a = odremed.error_signature('no window matching "ParaBank 12" here')
    b = odremed.error_signature('no window matching "ParaBank 34" here')
    assert a == b


def test_record_then_query_round_trips(tmp_path: pathlib.Path) -> None:
    memory = remem.RemediationMemory(
        store.RemediationsStore(tmp_path / "rem.json")
    )
    assert memory.query("sit", "err") is None
    memory.record("sit", "err", "alternate_action", "click by coordinates")
    got = memory.query("sit", "err")
    assert got is not None
    assert got.kind == "alternate_action"
    assert got.hint == "click by coordinates"
    assert got.applied == 1


def test_record_reinforces_and_persists(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "rem.json"
    first = remem.RemediationMemory(store.RemediationsStore(path))
    first.record("sit", "err", "alternate_action", "use select")
    first.record("sit", "err", "alternate_action", "use select")
    assert first.query("sit", "err").applied == 2
    # A fresh memory loads what was persisted.
    second = remem.RemediationMemory(store.RemediationsStore(path))
    reloaded = second.query("sit", "err")
    assert reloaded is not None and reloaded.applied == 2


def test_corrupt_store_reads_empty(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "rem.json"
    path.write_text("{ not json")
    memory = remem.RemediationMemory(store.RemediationsStore(path))
    assert memory.query("sit", "err") is None
