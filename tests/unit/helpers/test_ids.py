"""
Record ids are checked before they name a file.
"""

from __future__ import annotations

import pytest

import operant.domain.errors as errors
import operant.helpers.ids as ids


@pytest.mark.parametrize("key", ["savings-balance", "parabank", "v1.2_x"])
def test_plain_names_pass(key: str) -> None:
    assert ids.checked_key(key) == key


@pytest.mark.parametrize("key", ["", "../x", "a/b", ".hidden", "a\\b", "x" * 200])
def test_path_like_names_are_refused(key: str) -> None:
    with pytest.raises(errors.InvalidIdError):
        ids.checked_key(key)
