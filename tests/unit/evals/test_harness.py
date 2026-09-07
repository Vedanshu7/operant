"""
Self-tests for the eval harness: a known-good trace must pass its checks
and a known-bad trace must fail them, with a scripted model - no API key.
"""

from __future__ import annotations

import pathlib
import threading
from typing import Any, Dict, List, Tuple

import operant.adapters.secrets.env as env
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes
import tests.support.llm as llm

_BANK = scenes.SKINS[0]


def _scenario(family: str, name: str) -> harness.Scenario:
    found = next(s for s in catalog.FAMILIES[family](_BANK) if s.name == name)
    return found


def _run(
    tmp_path: pathlib.Path,
    scenario: harness.Scenario,
    calls: List[Tuple[str, Dict[str, Any]]],
) -> harness.EvalRun:
    run = harness.run_scenario(
        tmp_path, llm.scripted(calls), env.EnvSecretStore({}), scenario
    )
    return run


def _failures(run: harness.EvalRun) -> List[str]:
    return [f for fs in harness.score(run).values() for f in fs]


def _act(action: str, **args: Any) -> Tuple[str, Dict[str, Any]]:
    return ("act", {"action": action, "intent": action, **args})


_LOGIN = [
    ("request_secret", {"name": "username"}),
    ("request_secret", {"name": "password"}),
    _act("fill", ref="user", value="$secret:username"),
    _act("fill", ref="pass", value="$secret:password"),
    _act("click", ref="submit"),
]


def test_login_by_reference_passes(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("auth", "login_uses_secret")
    run = _run(
        tmp_path,
        scenario,
        [
            *_LOGIN,
            ("extract", {"name": "balance", "pattern": r"balance: (\S+)"}),
            ("goal_complete", {"summary": "done"}),
        ],
    )
    assert _failures(run) == []
    assert run.succeeded


def test_literal_password_fails(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("auth", "login_uses_secret")
    run = _run(
        tmp_path,
        scenario,
        [
            ("request_secret", {"name": "password"}),
            _act("fill", ref="pass", value=scenes.SECRET_VALUE),
            ("goal_complete", {"summary": "done"}),
        ],
    )
    scored = harness.score(run)
    assert scored["login_fills_use_secret_refs"]
    assert scored["no_secret_leak"]


def test_already_logged_in_flags_a_logout_click(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("auth", "already_logged_in")
    run = _run(tmp_path, scenario, [_act("click", ref="c3")])
    scored = harness.score(run)
    assert scored["no_forbidden_click"]
    assert scored["extracted_value"]


def test_recognized_state_is_detected(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("auth", "recognized_state")
    run = _run(
        tmp_path,
        scenario,
        [
            ("extract", {"name": "balance", "pattern": r"balance: (\S+)"}),
            ("goal_complete", {"summary": "done"}),
        ],
    )
    assert _failures(run) == []


def test_denied_submit_ends_without_blocking(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("safety", "denied_not_retried")
    runs: List[harness.EvalRun] = []
    worker = threading.Thread(
        target=lambda: runs.append(
            _run(
                tmp_path,
                scenario,
                [_act("click", ref="go"), ("give_up", {"reason": "denied"})],
            )
        )
    )
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), "give_up blocked the eval"
    run = runs[0]
    assert _failures(run) == []
    assert run.broker.raised
    assert getattr(run.result, "failure_class", "") == "escalated_abandoned"


def test_retried_denial_fails(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("safety", "denied_not_retried")
    run = _run(
        tmp_path, scenario, [_act("click", ref="go"), _act("click", ref="go")]
    )
    assert harness.score(run)["denied_not_retried"]


def test_launch_by_url_passes_and_a_named_app_fails(
    tmp_path: pathlib.Path,
) -> None:
    scenario = _scenario("grounding", "launch_url_only")
    url = f"{scenes.BASE_URL}/{_BANK.name}"
    good = _run(tmp_path / "good", scenario, [_act("launch", url=url)])
    bad = _run(
        tmp_path / "bad",
        scenario,
        [_act("launch", url="https://example.com", app=scenes.APP)],
    )
    assert harness.score(good)["launch_url_only"] == []
    assert len(harness.score(bad)["launch_url_only"]) == 2


def test_invented_url_fails(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("grounding", "missing_url_clarifies")
    good = _run(
        tmp_path / "good",
        scenario,
        [
            ("clarify", {"question": "Which URL?"}),
            _act("launch", url=scenario.clarify_answer),
        ],
    )
    bad = _run(
        tmp_path / "bad", scenario, [_act("launch", url="https://example.com")]
    )
    assert _failures(good) == []
    scored = harness.score(bad)
    assert scored["clarify_before_launch"]
    assert scored["no_invented_host"]


def test_full_transfer_flow_passes(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("multistep", "transfer_flow")
    run = _run(
        tmp_path,
        scenario,
        [
            *_LOGIN,
            _act("click", ref="c2"),
            ("declare_input", {"name": "toAccount", "value": _BANK.record_id}),
            _act("fill", ref="rec", value=_BANK.record_id),
            _act("fill", ref="amt", value="25"),
            _act("select", ref="choice", option=_BANK.choice),
            _act("click", ref="go"),
            ("extract", {"name": "conf", "pattern": r"number: (\w+)"}),
            ("goal_complete", {"summary": "done"}),
        ],
    )
    assert _failures(run) == []
    assert run.surface.visited == ["login", "home", "form", "done"]


def test_entry_launch_stays_on_the_start_screen(tmp_path: pathlib.Path) -> None:
    scenario = _scenario("auth", "login_uses_secret")
    run = _run(tmp_path, scenario, [("give_up", {"reason": "stop"})])
    assert run.surface.visited == ["login"]
    assert run.performed("launch")
