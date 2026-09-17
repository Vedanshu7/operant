"""
Single-vs-multi scorecard tests.

Cover the interval, pass^k and percentile maths, and the rendered table.
"""

from typing import Any, Dict

import pytest

import tests.evals.compare as evcompar


def _row(mode: str, scenario: str, passed: bool, **over):
    row = {
        "mode": mode,
        "scenario": scenario,
        "skin": "bank",
        "family": "safety",
        "passed": passed,
        "tokens_in": 1000,
        "tokens_out": 100,
        "turns": 4,
        "role_calls": {"planner": 1, "verifier": 2} if mode == "multi" else {},
        "trajectory": {
            "steps": 4.0,
            "reference_steps": 2.0,
            "efficiency": 0.5,
            "in_order": 1.0,
        },
    }
    row.update(over)
    return row


def test_wilson_interval_matches_the_textbook_value() -> None:
    low, high = evcompar.wilson(9, 10)
    assert low == pytest.approx(0.596, abs=0.001)
    assert high == pytest.approx(0.982, abs=0.001)
    assert evcompar.wilson(0, 0) == (0.0, 0.0)


def test_pass_hat_k_needs_every_trial_to_pass() -> None:
    two_of_three = [_row("single", "a", ok) for ok in (True, True, False)]
    assert evcompar.pass_hat_k(two_of_three, 3) == 0.0
    three_of_four = [_row("single", "a", ok) for ok in (True, True, True, False)]
    assert evcompar.pass_hat_k(three_of_four, 3) == pytest.approx(0.25)
    assert evcompar.pass_hat_k(two_of_three[:2], 3) is None


def test_percentile_is_nearest_rank() -> None:
    assert evcompar.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert evcompar.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.95) == 5.0


def test_the_scorecard_compares_both_modes() -> None:
    rows = [
        _row("single", "a", True, duration_s=10.0),
        _row("single", "a", False, duration_s=20.0),
        _row("multi", "a", True),
    ]
    table = evcompar.scorecard(rows, lambda row: 0.01, k=2)
    lines = {line.split(" | ")[0]: line for line in table.splitlines()}
    assert lines["| Pass rate (95% CI)"].startswith("| Pass rate (95% CI) | 50%")
    assert "$0.0200" in lines["| Cost per passed trial"]
    assert lines["| Model calls per trial"].endswith("| 4.0 | 7.0 |")
    assert lines["| Seconds per trial (p50 / p95)"].endswith(
        "| 10.0 / 20.0 | not recorded |"
    )


def test_the_role_table_prices_each_role_at_its_own_model() -> None:
    usage = {"calls": 2, "tokens_in": 1000, "tokens_out": 10, "seconds": 3.0}
    rows = [
        _row(
            "multi",
            "a",
            True,
            roles={
                "executor": {**usage, "model": "big"},
                "verifier": {**usage, "model": "small"},
            },
        )
    ]
    prices = {"big": 0.5, "small": 0.1}
    table = evcompar.role_table(rows, lambda model, tin, tout: prices[model])
    assert (
        "| multi | executor | big | 2.0 | 1,000 / 10 | $0.5000 | 3.0 |" in table
    )
    assert (
        "| multi | verifier | small | 2.0 | 1,000 / 10 | $0.1000 | 3.0 |" in table
    )
    assert "not recorded" in evcompar.role_table([_row("single", "a", True)], max)


def _live(kind: str, agents: str, status: str, seconds: float) -> Dict[str, Any]:
    return {
        "kind": kind,
        "agents": agents,
        "status": status,
        "capability_id": "cap",
        "started_at": "2026-10-22T10:00:00+00:00",
        "finished_at": f"2026-10-22T10:00:{seconds:02.0f}+00:00",
    }


def test_the_live_table_times_succeeded_runs_and_the_replay_speed_up() -> None:
    table = evcompar.live_table(
        [
            _live("discovery", "single", "succeeded", 30),
            _live("discovery", "single", "failed", 2),
            _live("replay", "multi", "succeeded", 6),
            _live("replay", "single", "running", 1),
        ]
    )
    assert "| discovery | single | 2 | 50% | 30.0 / 30.0 | 120 |" in table
    assert "| replay | - | 1 | 100% | 6.0 / 6.0 | 600 |" in table
    assert "Replay speed-up for cap: 5.0x" in table
