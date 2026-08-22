"""
Value-free structural fingerprints identify a screen by its content.
"""

from __future__ import annotations

from typing import Optional

import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest


def _box() -> digest.Box:
    return digest.Box(x=0.0, y=0.0, w=0.1, h=0.1)


def _control(role: str, name: str, path: str, value: Optional[str] = None):
    return digest.Control(
        ref="r",
        role=role,
        name=name,
        label="",
        path=path,
        box=_box(),
        value=value,
    )


def _screen(*controls: digest.Control) -> digest.ScreenDigest:
    return digest.ScreenDigest(
        app="Chrome", window_title="Welcome", text="", controls=controls
    )


def test_of_is_value_free_across_balances_dates_and_row_counts() -> None:
    lo = _screen(
        _control("link", "Account 12345 - $2,550.00", "content>table>row:1>link"),
        _control("link", "Account 67890 - $10.00", "content>table>row:2>link"),
    )
    hi = _screen(
        _control("link", "Account 99 - $1.00", "content>table>row:1>link"),
    )
    # Values, account numbers, and row counts differ; fingerprint is equal.
    assert odfinger.of(lo) == odfinger.of(hi)


def test_logged_in_and_logged_out_are_distinct() -> None:
    out = _screen(
        _control("textfield", "Username", "content>form>textfield"),
        _control("textfield", "Password", "content>form>textfield"),
        _control("button", "Log In", "content>form>button"),
    )
    inn = _screen(
        _control("link", "Accounts Overview", "content>menu>link"),
        _control("link", "Log Out", "content>menu>link"),
    )
    assert odfinger.of(out) != odfinger.of(inn)
    assert odfinger.coverage(odfinger.of(out), set(odfinger.of(inn))) == 0.0


def test_coverage_is_recall_tolerant_of_extra_controls() -> None:
    node_fp = odfinger.of(
        _screen(
            _control("link", "Accounts Overview", "content>menu>link"),
            _control("link", "Log Out", "content>menu>link"),
        )
    )
    live = _screen(
        _control("link", "Accounts Overview", "content>menu>link"),
        _control("link", "Log Out", "content>menu>link"),
        _control("link", "Account 5 - $9", "content>table>row:1>link"),
    )
    assert odfinger.coverage(node_fp, set(odfinger.of(live))) == 1.0
