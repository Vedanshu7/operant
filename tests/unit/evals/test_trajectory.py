"""
Trajectory-metric tests with scripted runs: scoring against reference
trajectories, and labelling verifier verdicts against the screen.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Dict, List, Tuple

import operant.adapters.secrets.env as env
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes
import tests.evals.trajectory as trajecto
import tests.support.llm as sllm

_BANK = scenes.SKINS[0]
Call = Tuple[str, Dict[str, Any]]


def _act(action: str, **args: Any) -> Call:
    return ("act", {"action": action, "intent": action, **args})


_LOGIN: List[Call] = [
    ("request_secret", {"name": "username"}),
    ("request_secret", {"name": "password"}),
    _act("fill", ref="user", value="$secret:username"),
    _act("fill", ref="pass", value="$secret:password"),
    _act("click", ref="submit"),
]
_FORM: List[Call] = [
    ("declare_input", {"name": "toAccount", "value": _BANK.record_id}),
    ("declare_input", {"name": "amount", "value": "25"}),
    ("declare_input", {"name": "fromAccount", "value": _BANK.choice}),
    _act("fill", ref="rec", value=_BANK.record_id),
    _act("fill", ref="amt", value="25"),
    _act("select", ref="choice", option=_BANK.choice),
    _act("click", ref="go"),
]
_FINISH: List[Call] = [
    ("extract", {"name": "conf", "pattern": r"number: (\w+)"}),
    ("goal_complete", {"summary": "done"}),
]
_IDEAL = [*_LOGIN, _act("click", ref="c2"), *_FORM, *_FINISH]


def _scenario(name: str, mode: str = "single") -> harness.Scenario:
    found = next(
        s
        for build in catalog.FAMILIES.values()
        for s in build(_BANK)
        if s.name == name
    )
    return dataclasses.replace(found, mode=mode)


def _run(
    tmp_path: pathlib.Path,
    scenario: harness.Scenario,
    calls: List[Call],
    roles: Dict[str, List[Call]] | None = None,
) -> harness.EvalRun:
    run = harness.run_scenario(
        tmp_path,
        harness.EvalEnv(
            sllm.scripted(calls),
            env.EnvSecretStore({}),
            role_llms={r: sllm.scripted(c) for r, c in (roles or {}).items()},
        ),
        scenario,
    )
    return run


def test_the_ideal_trajectory_scores_perfectly(tmp_path: pathlib.Path) -> None:
    run = _run(tmp_path, _scenario("transfer_flow"), _IDEAL)
    scored = trajecto.metrics(run)
    assert scored is not None
    assert (scored["recall"], scored["precision"], scored["efficiency"]) == (
        1,
        1,
        1,
    )
    assert scored["in_order"] == 1.0


def test_extra_steps_lower_precision_and_efficiency(
    tmp_path: pathlib.Path,
) -> None:
    wandering = [
        *_LOGIN,
        _act("click", ref="c1"),
        _act("click", ref="c2"),
        _act("scroll", direction="down"),
        *_FORM,
        *_FINISH,
    ]
    scored = trajecto.metrics(
        _run(tmp_path, _scenario("transfer_flow"), wandering)
    )
    assert scored is not None
    assert scored["recall"] == 1.0
    assert scored["efficiency"] < 1.0 and scored["precision"] < 1.0


def test_a_missing_step_lowers_recall(tmp_path: pathlib.Path) -> None:
    skipped = [c for c in _IDEAL if c[0] != "request_secret"]
    scored = trajecto.metrics(_run(tmp_path, _scenario("transfer_flow"), skipped))
    assert scored is not None
    assert scored["recall"] < 1.0 and scored["in_order"] == 0.0


def test_pressing_enter_counts_as_submitting_the_login() -> None:
    reference = trajecto.REFERENCE["login_uses_secret"]
    taken = [
        "request_secret",
        "request_secret",
        "act:fill:user",
        "act:fill:pass",
        "act:press",
        "extract",
        "goal_complete",
    ]
    assert trajecto.in_order_match(reference, taken) == len(reference)


def test_every_catalog_scenario_has_a_reference() -> None:
    names = {s.name for build in catalog.FAMILIES.values() for s in build(_BANK)}
    assert names <= set(trajecto.REFERENCE)
    assert names <= set(trajecto.SUCCESS_SCREENS)


def _multi_roles(verdict: bool) -> Dict[str, List[Call]]:
    plan = {
        "subgoals": [
            {"id": "s1", "description": "do it", "success_criteria": "done shown"}
        ]
    }
    return {
        "planner": [("submit_plan", plan)],
        "verifier": [("verdict", {"passed": verdict, "reason": "checked"})] * 3,
        "safety": [("verdict", {"passed": True, "reason": "ok"})] * 3,
    }


def test_a_correct_accept_is_a_true_accept(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path, _scenario("transfer_flow", "multi"), _IDEAL, _multi_roles(True)
    )
    assert trajecto.verifier_confusion(run)["true_accept"] == 1


def test_accepting_a_pending_screen_is_a_false_accept(
    tmp_path: pathlib.Path,
) -> None:
    calls = [
        *_LOGIN,
        _act("click", ref="c2"),
        *_FORM,
        ("goal_complete", {"summary": "x"}),
    ]
    run = _run(
        tmp_path,
        _scenario("premature_complete", "multi"),
        calls,
        _multi_roles(True),
    )
    labels = trajecto.verifier_confusion(run)
    assert labels["false_accept"] == 1


def test_rejecting_a_pending_screen_is_a_true_reject(
    tmp_path: pathlib.Path,
) -> None:
    calls = [
        *_LOGIN,
        _act("click", ref="c2"),
        *_FORM,
        ("goal_complete", {"summary": "x"}),
    ]
    run = _run(
        tmp_path,
        _scenario("premature_complete", "multi"),
        calls,
        _multi_roles(False),
    )
    assert trajecto.verifier_confusion(run)["true_reject"] >= 1


def test_summaries_average_metrics_and_rate_verifier_errors() -> None:
    rows = [
        {
            "trajectory": {
                "recall": 1.0,
                "precision": 0.5,
                "efficiency": 0.5,
                "in_order": 1.0,
            },
            "verifier": {"true_accept": 1, "false_accept": 1},
        },
        {
            "trajectory": {
                "recall": 0.5,
                "precision": 1.0,
                "efficiency": 1.0,
                "in_order": 0.0,
            },
            "verifier": {"true_reject": 2, "false_reject": 0},
        },
    ]
    summary = trajecto.summarize(rows)
    assert summary["recall"] == 0.75 and summary["efficiency"] == 0.75
    assert summary["false_accept_rate"] == 0.5
    assert summary["false_reject_rate"] == 0.0
