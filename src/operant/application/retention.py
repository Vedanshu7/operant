"""
Deleting old evidence runs.

Evidence holds screenshots and the run log of everything a run saw, so
it is kept only as long as the operator decides.

Import as:

import operant.application.retention as apretent
"""

from __future__ import annotations

import pathlib
import shutil
from typing import List

import operant.helpers.time as time


def expired_runs(
    evidence_dir: pathlib.Path, *, max_age_days: float, now: float
) -> List[pathlib.Path]:
    """
    Return the run directories last written more than ``max_age_days`` ago.

    :param evidence_dir: The directory holding one directory per run.
    :param max_age_days: Age past which a run is expired.
    :param now: The current time, in seconds since the epoch.
    :return: Expired run directories, oldest name first.
    """
    cutoff = now - max_age_days * time.SECONDS_PER_DAY
    expired = [
        run_dir
        for run_dir in sorted(evidence_dir.iterdir())
        if run_dir.is_dir() and _last_written(run_dir) < cutoff
    ]
    return expired


def delete_runs(run_dirs: List[pathlib.Path]) -> None:
    """
    Delete each run directory and everything in it.
    """
    for run_dir in run_dirs:
        shutil.rmtree(run_dir)


def _last_written(run_dir: pathlib.Path) -> float:
    """
    Return when anything in the run directory was last written.
    """
    times = [path.stat().st_mtime for path in run_dir.rglob("*")]
    last = max(times, default=run_dir.stat().st_mtime)
    return last
