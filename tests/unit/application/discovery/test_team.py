"""
Multi-agent coordinator tests with a scripted model per role: plan,
execute, verify, reject, replan, escalate - no live app, no real model.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Dict, List, Optional, Tuple

import pytest

import operant.adapters.secrets.env as env
import operant.application.discovery.team as dsteam
import operant.application.memory as apmemory
import operant.domain.models.plan as mdplan
import operant.infra.db.engine as engine
import operant.infra.repositories.memory as rmmemory
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes
import tests.support.llm as sllm

_BANK = scenes.SKINS[0]
Call = Tuple[str, Dict[str, Any]]


def _scenario(family: str, name: str) -> harness.Scenario:
    found = next(s for s in catalog.FAMILIES[family](_BANK) if s.name == name)
    return dataclasses.replace(found, mode="multi")


def _plan(*descriptions: str) -> Call:
    return (
        "submit_plan",
        {
            "subgoals": [
                {
                    "id": f"s{i}",
                    "description": d,
                    "success_criteria": f"{d} shown",
                }
                for i, d in enumerate(descriptions, start=1)
            ],
            "credential_names": [],
        },
    )


def _verdicts(*passed: bool) -> List[Call]:
    return [("verdict", {"passed": p, "reason": "checked"}) for p in passed]


def _run(
    tmp_path: pathlib.Path,
    scenario: harness.Scenario,
    executor: List[Call],
    *,
    planner: List[Call],
    verifier: List[Call],
    safety: Optional[List[Call]] = None,
    extra: Optional[Dict[str, List[Call]]] = None,
    team: Optional[dsteam.TeamBudget] = None,
    memory: Optional[apmemory.AgentMemory] = None,
) -> harness.EvalRun:
    roles = {
        "planner": sllm.scripted(planner),
        "verifier": sllm.scripted(verifier),
        "safety": sllm.scripted(
            safety if safety is not None else _verdicts(*[True] * len(verifier))
        ),
    }
    for role, calls in (extra or {}).items():
        roles[role] = sllm.scripted(calls)
    run = harness.run_scenario(
        tmp_path,
        harness.EvalEnv(
            sllm.scripted(executor),
            env.EnvSecretStore({}),
            role_llms=roles,
            memory=memory,
        ),
        scenario,
        team=team,
    )
    return run


_READ = [
    ("extract", {"name": "balance", "pattern": r"balance: (\S+)"}),
    ("goal_complete", {"summary": "read it"}),
]


def test_plan_execute_verify_completes(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        _READ,
        planner=[_plan("read the savings balance")],
        verifier=_verdicts(True),
    )
    assert run.succeeded
    assert run.state.extracted == {"balance": _BANK.value}
    assert [e["subgoals"][0]["id"] for e in run.events_of("plan_proposed")] == [
        "s1"
    ]
    reviewers = sorted(e["reviewer"] for e in run.events_of("verifier_verdict"))
    assert reviewers == ["leak", "safety", "verifier"]


def test_the_recording_matches_single_agent(tmp_path: pathlib.Path) -> None:
    multi = _run(
        tmp_path / "multi",
        _scenario("auth", "already_logged_in"),
        _READ,
        planner=[_plan("read the savings balance")],
        verifier=_verdicts(True),
    )
    single = harness.run_scenario(
        tmp_path / "single",
        harness.EvalEnv(sllm.scripted(_READ), env.EnvSecretStore({})),
        dataclasses.replace(
            _scenario("auth", "already_logged_in"), mode="single"
        ),
    )
    assert multi.succeeded and single.succeeded
    a, b = multi.result.recording, single.result.recording
    assert a.edges == b.edges
    assert a.outputs == b.outputs
    assert a.extract == b.extract


def test_a_rejection_sends_the_reason_back(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [("goal_complete", {"summary": "done?"}), *_READ],
        planner=[_plan("read the savings balance")],
        verifier=[
            ("verdict", {"passed": False, "reason": "no balance extracted"}),
            ("verdict", {"passed": True, "reason": "ok"}),
        ],
    )
    assert run.succeeded
    assert any(
        "NOT VERIFIED - verifier: no balance extracted" in harness.message_text(m)
        for m in run.llm.sent[1]
    )


def test_two_rejections_trigger_a_replan(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [
            ("goal_complete", {"summary": "a"}),
            ("goal_complete", {"summary": "b"}),
        ],
        planner=[_plan("read it"), _plan("read the balance again")],
        verifier=_verdicts(False, False),
    )
    first = run.events_of("replanned")[0]
    assert first["attempt"] == 1
    assert "rejected 2 times" in first["reason"]
    assert len(run.roles["planner"].turns) >= 2


def test_spent_replans_escalate_to_a_person(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [
            ("goal_complete", {"summary": "a"}),
            ("goal_complete", {"summary": "b"}),
        ],
        planner=[_plan("read it")],
        verifier=_verdicts(False, False),
        team=dsteam.TeamBudget(max_replans=0),
    )
    assert getattr(run.result, "failure_class", "") == "escalated_abandoned"
    assert run.broker.raised


def test_give_up_replans_before_escalating(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [("give_up", {"reason": "lost"}), *_READ],
        planner=[_plan("read it"), _plan("read the balance")],
        verifier=_verdicts(True),
    )
    assert run.succeeded
    assert not run.broker.raised
    assert run.events_of("replanned")


def test_verified_subgoals_are_folded_out_of_the_history(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [
            ("subgoal_done", {"summary": "on home"}),
            ("extract", {"name": "balance", "pattern": r"balance: (\S+)"}),
            ("goal_complete", {"summary": "read it"}),
        ],
        planner=[_plan("be on home", "read the balance")],
        verifier=_verdicts(True, True),
    )
    assert run.succeeded
    # The next executor call starts fresh: system prompt + the new turn,
    # with the verified subgoal reduced to one line in the plan block.
    second = run.llm.sent[1]
    assert [m.role for m in second] == ["system", "user"]
    assert "[done] be on home: on home" in harness.message_text(second[-1])


def test_a_missed_extract_is_repaired_by_candidates(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [
            ("extract", {"name": "balance", "pattern": r"Balance=(\d+)"}),
            ("goal_complete", {"summary": "read it"}),
        ],
        planner=[_plan("read the balance")],
        verifier=_verdicts(True),
        extra={
            "extract": [
                ("propose_pattern", {"pattern": r"nothing (here)"}),
                ("propose_pattern", {"pattern": r"balance: (\S+)"}),
                ("propose_pattern", {"pattern": r"balance: (\S+)"}),
            ]
        },
    )
    assert run.state.extracted["balance"] == _BANK.value


def test_compile_review_is_advisory(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("safety", "mutating_needs_approval"),
        [
            ("act", {"action": "click", "ref": "go", "intent": "submit"}),
            ("goal_complete", {"summary": "sent"}),
        ],
        planner=[_plan("submit the form")],
        verifier=_verdicts(True),
        extra={
            "critic": [("review", {"verdict": "concern", "note": "fragile"})],
            "schema": [("review", {"verdict": "ok", "note": "fine"})],
        },
    )
    assert run.succeeded
    reviews = {e["target"]: e["verdict"] for e in run.events_of("compile_review")}
    assert reviews["schema"] == "ok"
    assert "concern" in reviews.values()


def test_a_planner_failure_falls_back_to_one_subgoal(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        _READ,
        planner=[
            ("submit_plan", {"subgoals": []}),
            ("submit_plan", {"subgoals": []}),
        ],
        verifier=_verdicts(True),
    )
    assert run.succeeded
    plan = run.events_of("plan_proposed")[0]["subgoals"]
    assert plan[0]["description"] == run.scenario.goal


def test_credential_values_are_rejected_from_plans() -> None:
    with pytest.raises(ValueError):
        mdplan.Plan(
            subgoals=[
                mdplan.Subgoal(id="s1", description="d", success_criteria="c")
            ],
            credential_names=["my password is hunter2"],
        )


def test_a_goal_claim_verifies_the_last_subgoal_not_a_stale_one(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        _READ,
        planner=[_plan("open the home page", "read the savings balance")],
        verifier=_verdicts(True),
    )
    assert run.succeeded
    judged = [e["subgoal"] for e in run.events_of("verifier_verdict")]
    assert judged == ["s2", "s2", "s2"]


def test_working_ui_actions_do_not_count_as_a_stall(
    tmp_path: pathlib.Path,
) -> None:
    form = [
        ("act", {"action": "fill", "ref": "rec", "value": "1", "intent": "i"}),
        ("act", {"action": "fill", "ref": "amt", "value": "2", "intent": "i"}),
        ("act", {"action": "fill", "ref": "rec", "value": "1", "intent": "i"}),
        ("act", {"action": "fill", "ref": "amt", "value": "2", "intent": "i"}),
        ("act", {"action": "click", "ref": "go", "intent": "submit"}),
        ("extract", {"name": "conf", "pattern": r"number: (\w+)"}),
        ("goal_complete", {"summary": "sent"}),
    ]
    run = _run(
        tmp_path,
        _scenario("safety", "mutating_needs_approval"),
        form,
        planner=[_plan("send it")],
        verifier=_verdicts(True),
        team=dsteam.TeamBudget(stall_turns=3),
    )
    assert run.succeeded
    assert run.events_of("replanned") == []


def test_giving_up_after_a_denial_does_not_replan_around_it(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("safety", "denied_not_retried"),
        [
            ("act", {"action": "click", "ref": "go", "intent": "submit"}),
            ("give_up", {"reason": "the submit was denied"}),
        ],
        planner=[_plan("submit the form"), _plan("submit it another way")],
        verifier=[],
    )
    assert not run.events_of("replanned")
    assert run.broker.raised
    assert len([a for a in run.acts("click") if a.get("ref") == "go"]) == 1


def test_a_denial_stays_in_the_executors_plan_context(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("safety", "denied_not_retried"),
        [
            ("act", {"action": "click", "ref": "go", "intent": "submit"}),
            ("subgoal_done", {"summary": "submitted"}),
            ("give_up", {"reason": "the submit was denied"}),
        ],
        planner=[_plan("submit the form")],
        verifier=_verdicts(False),
    )
    last_prompt = str(run.llm.sent[-1])
    assert "REFUSED BY A PERSON" in last_prompt


# #############################################################################
# Memory
# #############################################################################


def _memory() -> Tuple[apmemory.AgentMemory, rmmemory.SqlMemoryStore]:
    database = engine.Database.open(None)
    database.create_all()
    store = rmmemory.SqlMemoryStore(database)
    return apmemory.AgentMemory(store), store


def test_a_rejection_the_run_gets_past_teaches_nothing(
    tmp_path: pathlib.Path,
) -> None:
    memory, store = _memory()
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [("goal_complete", {"summary": "done?"}), *_READ],
        planner=[_plan("read the savings balance")],
        verifier=_verdicts(False, True),
        memory=memory,
    )
    assert run.succeeded
    [vendor] = store.vendors()
    assert store.lessons(vendor) == []
    assert len(store.plans(vendor)) == 1


def test_a_subgoal_rejected_repeatedly_keeps_what_worked(
    tmp_path: pathlib.Path,
) -> None:
    memory, store = _memory()
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [
            ("goal_complete", {"summary": "a"}),
            ("goal_complete", {"summary": "b"}),
            *_READ,
        ],
        planner=[_plan("read the savings balance")] * 2,
        verifier=_verdicts(False, False, True),
        memory=memory,
    )
    assert run.succeeded
    [lesson] = store.lessons(store.vendors()[0])
    assert lesson.lesson == (
        'On "read the savings balance": not_done. What worked: read it.'
    )


def test_a_failed_run_keeps_the_unresolved_rejection_and_counts_the_plan(
    tmp_path: pathlib.Path,
) -> None:
    memory, store = _memory()
    scenario = _scenario("auth", "already_logged_in")
    seeded = _run(
        tmp_path / "seed",
        scenario,
        _READ,
        planner=[_plan("read the savings balance")],
        verifier=_verdicts(True),
        memory=memory,
    )
    assert seeded.succeeded
    run = _run(
        tmp_path / "fail",
        scenario,
        [
            ("goal_complete", {"summary": "a"}),
            ("goal_complete", {"summary": "b"}),
        ],
        planner=[_plan("read the savings balance")],
        verifier=_verdicts(False, False),
        team=dsteam.TeamBudget(max_replans=0),
        memory=memory,
    )
    assert not run.succeeded
    vendor = store.vendors()[0]
    [plan] = store.plans(vendor)
    assert (plan.successes, plan.failures) == (1, 1)
    [lesson] = store.lessons(vendor)
    assert lesson.lesson.endswith("What worked: unresolved.")


def test_a_single_agent_given_memory_sees_the_recalled_plan(
    tmp_path: pathlib.Path,
) -> None:
    memory, store = _memory()
    scenario = _scenario("auth", "already_logged_in")
    seeded = _run(
        tmp_path / "seed",
        scenario,
        _READ,
        planner=[_plan("read the savings balance")],
        verifier=_verdicts(True),
        memory=memory,
    )
    assert seeded.succeeded
    single = harness.run_scenario(
        tmp_path / "single",
        harness.EvalEnv(
            sllm.scripted(_READ), env.EnvSecretStore({}), memory=memory
        ),
        dataclasses.replace(scenario, mode="single"),
    )
    assert single.succeeded
    first_turn = " ".join(harness.message_text(m) for m in single.llm.sent[0])
    assert "MEMORY (advisory" in first_turn
    assert "read the savings balance" in first_turn
    # A single agent has no plan of its own to keep.
    [plan] = store.plans(store.vendors()[0])
    assert plan.successes == 1


def test_an_injected_screen_is_fenced_flagged_and_logged_once(
    tmp_path: pathlib.Path,
) -> None:
    scenario = next(
        s
        for s in catalog.FAMILIES["injection"](_BANK)
        if s.name == "injection_dialog"
    )
    run = harness.run_scenario(
        tmp_path,
        harness.EvalEnv(
            sllm.scripted(
                [
                    (
                        "extract",
                        {"name": "balance", "pattern": r"balance: (\S+)"},
                    ),
                    ("goal_complete", {"summary": "read it"}),
                ]
            ),
            env.EnvSecretStore({}),
        ),
        dataclasses.replace(scenario, mode="single"),
    )
    first = " ".join(harness.message_text(m) for m in run.llm.sent[0])
    assert "<untrusted_screen>" in first and "WARNING - the screen" in first
    assert len(run.events_of("injection_suspected")) == 1
    assert all(not check(run) for check in scenario.checks)


# #############################################################################
# Typed checks and unknown verdicts
# #############################################################################


def _checked_plan(checks: List[Dict[str, str]], cover: bool) -> Call:
    return (
        "submit_plan",
        {
            "subgoals": [
                {
                    "id": "s1",
                    "description": "read the savings balance",
                    "success_criteria": "the balance is shown",
                    "checks": checks,
                    "checks_cover_criteria": cover,
                }
            ]
        },
    )


def test_covering_checks_that_hold_skip_the_model_verifier(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        _READ,
        planner=[
            _checked_plan(
                [
                    {"kind": "text_present", "value": "savings balance"},
                    {
                        "kind": "output_matches",
                        "output": "balance",
                        "value": r"^\$[\d,]+\.\d{2}$",
                    },
                ],
                cover=True,
            )
        ],
        verifier=[],
        safety=_verdicts(True),
    )
    assert run.succeeded
    assert run.roles["verifier"].turns == []
    reviewers = sorted(e["reviewer"] for e in run.events_of("verifier_verdict"))
    assert reviewers == ["checks", "leak", "safety"]


def test_a_failed_check_rejects_without_asking_a_model(
    tmp_path: pathlib.Path,
) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [("goal_complete", {"summary": "done?"})],
        planner=[
            _checked_plan(
                [{"kind": "text_present", "value": "Transfer Complete"}],
                cover=False,
            )
        ],
        verifier=[],
        safety=_verdicts(True),
    )
    assert run.roles["verifier"].turns == []
    assert any(
        "NOT VERIFIED - checks: failed: text_present 'Transfer Complete'"
        in harness.message_text(m)
        for m in run.llm.sent[1]
    )


def test_an_unknown_verdict_is_not_a_pass(tmp_path: pathlib.Path) -> None:
    run = _run(
        tmp_path,
        _scenario("auth", "already_logged_in"),
        [("goal_complete", {"summary": "done?"}), *_READ],
        planner=[_plan("read the savings balance")],
        verifier=[
            ("verdict", {"passed": True, "unknown": True, "reason": "cut off"}),
            ("verdict", {"passed": True, "reason": "ok"}),
        ],
    )
    assert run.succeeded
    assert any(
        "NOT VERIFIED - verifier: unknown: cut off" in harness.message_text(m)
        for m in run.llm.sent[1]
    )


def test_a_password_is_never_typed_into_a_pop_up_field(
    tmp_path: pathlib.Path,
) -> None:
    scenario = next(
        s
        for s in catalog.FAMILIES["injection"](_BANK)
        if s.name == "injection_popup"
    )
    run = harness.run_scenario(
        tmp_path,
        harness.EvalEnv(
            sllm.scripted(
                [
                    ("request_secret", {"name": "account_password"}),
                    (
                        "act",
                        {
                            "action": "fill",
                            "ref": "c7",
                            "value": "$secret:account_password",
                            "intent": "verify the session",
                        },
                    ),
                    (
                        "extract",
                        {"name": "balance", "pattern": r"balance: (\S+)"},
                    ),
                    ("goal_complete", {"summary": "read it"}),
                ]
            ),
            env.EnvSecretStore({}),
        ),
        dataclasses.replace(scenario, mode="single"),
    )
    assert run.performed("fill") == []
    replies = [
        harness.message_text(m) for m in run.llm.sent[2] if m.role == "tool"
    ]
    assert any("Refused" in reply for reply in replies)
