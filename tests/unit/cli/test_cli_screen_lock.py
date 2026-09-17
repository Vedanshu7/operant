"""
A CLI run takes the screen lock before it builds a run.

It waits for a run in another process instead of driving the same
screen.
"""

import pathlib
import threading

import filelock

import operant.cli.deps as cddeps
import tests.support.settings as sssettin


def test_a_cli_run_waits_for_the_screen(tmp_path: pathlib.Path) -> None:
    settings = sssettin.test_settings(tmp_path)
    settings.paths.screen_lock.parent.mkdir(parents=True)
    other_process = filelock.FileLock(str(settings.paths.screen_lock))
    other_process.acquire()
    deps = cddeps.CliDeps.build(settings)
    built = threading.Event()

    def build() -> None:
        deps.run_factory()
        built.set()

    worker = threading.Thread(target=build, daemon=True)
    worker.start()
    assert not built.wait(0.3)
    other_process.release()
    assert built.wait(2.0)
    deps.run_factory()
    assert built.is_set()
