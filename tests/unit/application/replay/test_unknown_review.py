"""
Replay never runs an unreviewed unknown step unattended.

A person reviews once, and later replays do not ask. A renamed control
is a different control, so it asks again.
"""

from __future__ import annotations

from typing import Set, Tuple

import operant.application.approval
import operant.application.replay.engine
import operant.application.usecases.replay as urreplay
import operant.domain.approval as approval
import operant.domain.fingerprint as odfinger
import operant.domain.graph.review as review
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.redaction
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.ports as ports
import tests.support.screens as screens
import tests.support.surfaces as surfaces
import tests.support.timing as timing

POLICY = policy.Policy(
    id="p",
    allowed_apps=["App"],
    allowed_url_patterns=[".*"],
    allowed_action_kinds=["click"],
    mutating_control_patterns=["send"],
    approval=approval.ApprovalPolicy(unknown="commit"),
)
EDGE = capab.edge(
    {
        "id": "e1",
        "from": "home",
        "to": "done",
        "description": "open reports",
        "action": {"kind": "click"},
        "risk": "unknown",
        "wait": {"kind": "settle", "timeout_ms": 1},
        "target": {
            "strategies": [
                {"kind": "role", "role": "link", "name": "Reports"},
                {"kind": "structural", "path": "w>link"},
            ],
            "reasoning": "r",
        },
    }
)


# #############################################################################
# _Surface
# #############################################################################


class _Surface(surfaces.GatedFakeSurface):

    def __init__(self, name: str = "Reports") -> None:
        super().__init__(POLICY)
        self.title = "App | Home"
        self.name = name

    def snapshot(self) -> digest.ScreenDigest:
        controls = (
            [
                screens.control(
                    ref="c0", role="link", name=self.name, path="w>link"
                )
            ]
            if self.title == "App | Home"
            else []
        )
        return screens.digest(controls, app="App", window_title=self.title)

    def apply(self, action) -> None:
        self.title = "App | Done"


# #############################################################################
# _Approvals
# #############################################################################


class _Approvals:

    def __init__(self) -> None:
        self.keys: Set[Tuple[str, str, str]] = set()

    def is_approved(self, vendor_id, graph_version, key) -> bool:
        return key in self.keys

    def record_outcome(
        self, vendor_id, graph_version, edge_id, *, passed
    ) -> None:
        pass

    def failing(self, vendor_id) -> Set[str]:
        return set()

    def approve(self, vendor_id, graph_version, keys, *, by) -> None:
        self.keys.update(keys)


def _replay(tmp_path, surface, approvals, approver=None):
    cap = capab.capability(start_node="home", goal_node="done")
    app_graph = graph.AppGraph(
        vendor_id=cap.vendor_id,
        nodes=[
            capab.node("home", r"App \| Home"),
            capab.node("done", r"App \| Done"),
        ],
        edges=[EDGE],
    )
    log = run_log.RunLog(
        tmp_path, "run", operant.domain.redaction.Redactor(), echo=False
    )
    opts = timing.fast_replay_options(
        tenant="t", params={}, retry_delay_s=0, edge_records=approvals
    )
    return operant.application.replay.engine.replay_path(
        cap,
        app_graph,
        [EDGE],
        surface,
        ports.quiet_broker(),
        log,
        log.redactor,
        opts,
        approver=approver,
    )


def test_an_unreviewed_step_is_refused_unattended(tmp_path) -> None:
    surface = _Surface()
    result = _replay(tmp_path, surface, _Approvals())
    assert result.status == "failure"
    assert result.failure.failure_class == "unreviewed_step"
    assert not urreplay.counts_toward_stability(result)
    assert surface.performed == []


def test_a_reviewed_step_replays_without_asking(tmp_path) -> None:
    approvals = _Approvals()
    approvals.keys.add(review.review_key(EDGE))
    surface = _Surface()
    assert _replay(tmp_path, surface, approvals).status == "success"


def test_a_renamed_control_asks_again(tmp_path) -> None:
    approvals = _Approvals()
    approvals.keys.add(review.review_key(EDGE))
    surface = _Surface(name="Analytics")
    assert _replay(tmp_path, surface, approvals).status == "failure"
    assert surface.performed == []


def test_digits_in_a_name_are_not_a_rename() -> None:
    assert review.review_key(EDGE, screens.control(name="Reports")) == (
        review.review_key(EDGE)
    )


def test_a_person_s_yes_during_a_run_is_kept(tmp_path) -> None:
    approvals = _Approvals()
    yes = ports.FakeApprover(approval.ApprovalDecision(approved=True))
    assert _replay(tmp_path, _Surface(), approvals, yes).status == "success"
    assert approvals.keys == {review.review_key(EDGE)}
    assert _replay(tmp_path / "again", _Surface(), approvals).status == "success"


def test_a_drifted_success_does_not_count_as_stable(tmp_path) -> None:
    approvals = _Approvals()
    approvals.keys.add(review.review_key(EDGE))
    cap = capab.capability(start_node="home", goal_node="done")
    recorded = screens.digest(
        [screens.control(role="link", name="Before", path="old>link")]
    )
    done = graph.Node(
        id="done",
        description="done",
        checks=[graph.TitleMatches(pattern=r"App \| Done")],
        fingerprint=odfinger.of(recorded),
    )
    app_graph = graph.AppGraph(
        vendor_id=cap.vendor_id,
        nodes=[capab.node("home", r"App \| Home"), done],
        edges=[EDGE],
    )
    log = run_log.RunLog(
        tmp_path, "run", operant.domain.redaction.Redactor(), echo=False
    )
    result = operant.application.replay.engine.replay_path(
        cap,
        app_graph,
        [EDGE],
        _Surface(),
        ports.quiet_broker(),
        log,
        log.redactor,
        timing.fast_replay_options(
            tenant="t", params={}, retry_delay_s=0, edge_records=approvals
        ),
    )
    assert result.status == "success"
    assert result.drifted == ["done"]
    assert urreplay.is_success(result)
    assert not urreplay.is_stable(result)


def test_a_person_s_refusal_is_a_decision_and_not_breakage(tmp_path) -> None:
    no = ports.FakeApprover(approval.ApprovalDecision(approved=False))
    result = _replay(tmp_path, _Surface(), _Approvals(), no)
    assert result.failure.failure_class == "approval_denied"
    assert not urreplay.counts_toward_stability(result)


def test_a_success_counts_unless_the_operator_cancelled(tmp_path) -> None:
    approvals = _Approvals()
    approvals.keys.add(review.review_key(EDGE))
    result = _replay(tmp_path, _Surface(), approvals)
    assert urreplay.counts_toward_stability(result)
    assert not urreplay.counts_toward_stability(result, cancelled=True)
