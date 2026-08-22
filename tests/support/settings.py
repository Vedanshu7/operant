"""
Settings builders for tests: everything under a temporary root.
"""

from __future__ import annotations

import pathlib

import operant.infra.settings as settings


def test_settings(root: pathlib.Path) -> settings.OperantSettings:
    """
    Build settings whose data directories all live under ``root``.

    :param root: Usually pytest's ``tmp_path``.
    :return: Settings with the env backend, no driver URL, and no
        ``.env``.
    """
    return settings.OperantSettings(
        paths=settings.PathsSettings(root=root),
        driver=settings.DriverSettings(url=None),
        secrets=settings.SecretsSettings(backend="env"),
    )
