"""
Evidence retention: only runs last written before the cutoff expire.
"""

import os
import pathlib

import operant.application.retention as apretent

DAY = 86400.0
NOW = 100 * DAY


def _run(root: pathlib.Path, name: str, written_days_ago: float) -> pathlib.Path:
    run_dir = root / name
    run_dir.mkdir()
    log = run_dir / "run-log.jsonl"
    log.write_text("{}")
    stamp = NOW - written_days_ago * DAY
    os.utime(log, (stamp, stamp))
    os.utime(run_dir, (stamp, stamp))
    return run_dir


def test_only_runs_older_than_the_cutoff_expire(tmp_path):
    old = _run(tmp_path, "replay-old", written_days_ago=40)
    fresh = _run(tmp_path, "replay-fresh", written_days_ago=2)
    (tmp_path / "notes.txt").write_text("not a run")
    expired = apretent.expired_runs(tmp_path, max_age_days=30, now=NOW)
    assert expired == [old]
    apretent.delete_runs(expired)
    assert not old.exists() and fresh.exists()


def test_a_run_written_to_recently_is_kept(tmp_path):
    run_dir = _run(tmp_path, "discovery-long", written_days_ago=40)
    shot = run_dir / "001-turn.png"
    shot.write_bytes(b"png")
    os.utime(shot, (NOW - DAY, NOW - DAY))
    assert apretent.expired_runs(tmp_path, max_age_days=30, now=NOW) == []
