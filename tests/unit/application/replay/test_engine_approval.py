"""
Approval gates at replay: unattended secret fills, gated caller-supplied.

sensitive values, cross-app export, mutating controls, denial/timeout/ default-
deny, remembering across replays, and redaction of sensitive outputs - over a
fake surface that enforces policy like the real guard.
"""

import json
from typing import Dict, List, Tuple

import pytest

import operant.application.approval
import operant.application.escalation
import operant.application.replay.engine
import operant.application.replay.options
import operant.domain.approval as approval
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.redaction
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.surfaces as surfaces

POLICY = policy.Policy(
    id="p",
    allowed_apps=["App"],
    allowed_url_patterns=[".*"],
    allowed_action_kinds=["launch", "click", "fill", "press", "select"],
    mutating_control_patterns=["send", "transfer"],
)


def _control(ref: str, role: str, name: str) -> digest.Control:
    return digest.Control(
        ref=ref,
        role=role,
        name=name,
        label="",
        path=f"w>{ref}",
        box=digest.Box(0.1, 0.1, 0.2, 0.05),
    )


SCREENS: Dict[str, Tuple[str, Tuple[digest.Control, ...]]] = {
    "App | Login": (
        "Customer Login",
        (
            _control("u", "text_field", "Username"),
            _control("p", "text_field", "Password"),
            _control("go", "button", "Log In"),
        ),
    ),
    "App | Home": (
        "Balance: $42.00",
        (
            _control("msg", "text_area", "Message"),
            _control("send", "button", "Send"),
        ),
    ),
    "App | Done": ("done", ()),
}


# #############################################################################
# AppSurface
# #############################################################################


class AppSurface(surfaces.GatedFakeSurface):
    """
    Every allowed action advances to the next scripted screen.
    """

    def __init__(self, titles: List[str], app: str = "App") -> None:
        super().__init__(POLICY)
        self._titles = list(titles)
        self.title = self._titles.pop(0)
        self.app = app

    def snapshot(self) -> digest.ScreenDigest:
        text, controls = SCREENS[self.title]
        return digest.ScreenDigest(
            app=self.app, window_title=self.title, text=text, controls=controls
        )

    def apply(self, action) -> None:
        if self._titles:
            self.title = self._titles.pop(0)


NODES = [
    capab.node("login", r"App \| Login"),
    capab.node("home", r"App \| Home"),
    capab.node("done", r"App \| Done"),
]


def _edge(eid, frm, to, action, target=None, role="text_field") -> graph.Edge:
    payload = {
        "id": eid,
        "from": frm,
        "to": to,
        "description": eid,
        "action": action,
        "wait": {"kind": "settle", "timeout_ms": 1},
    }
    if target:
        payload["target"] = {
            "strategies": [{"kind": "role", "role": role, "name": target}],
            "reasoning": "r",
        }
    return capab.edge(payload)


def _cap(vendor: str = "app", **over) -> artifact.CapabilityArtifact:
    over.setdefault(
        "tenants",
        {
            "t": artifact.TenantBinding(
                base_url="http://x", secret_refs={"password": "TEST_PW"}
            )
        },
    )
    over.setdefault("start_node", "login")
    over.setdefault("goal_node", "done")
    return capab.capability(vendor_id=vendor, **over)


def _run(
    tmp_path,
    cap,
    edges,
    surface,
    approver=None,
    *,
    params=None,
    origins=None,
    run="run",
):
    app_graph = graph.AppGraph(vendor_id=cap.vendor_id, nodes=NODES, edges=edges)
    log = run_log.RunLog(
        tmp_path, run, operant.domain.redaction.Redactor(), echo=False
    )
    broker = operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )
    opts = operant.application.replay.options.ReplayOptions(
        tenant="t", params=params or {}, output_origins=origins or {}
    )
    result = operant.application.replay.engine.replay_path(
        cap,
        app_graph,
        edges,
        surface,
        broker,
        log,
        log.redactor,
        opts,
        approver=approver,
    )
    return result, (tmp_path / run / "run-log.jsonl").read_text()


LOGIN = [
    _edge(
        "e1",
        "login",
        "home",
        {"kind": "fill", "value": {"secret_ref": "password"}},
        "Password",
    ),
    _edge(
        "e2",
        "home",
        "done",
        {"kind": "fill", "value": {"literal": "hi"}},
        "Message",
        role="text_area",
    ),
]
PII = [
    _edge(
        "e1",
        "login",
        "home",
        {"kind": "fill", "value": {"param": "ssn"}},
        "Username",
    ),
    LOGIN[1],
]
SSN = {"ssn": "123-45-6789"}


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("TEST_PW", "hunter2-pw")


def test_secret_fill_runs_unattended_and_never_exposes_the_value(tmp_path):
    approver = operant.application.approval.ScriptedApprover([])
    surface = AppSurface(["App | Login", "App | Home", "App | Done"])
    result, log_text = _run(tmp_path, _cap(), LOGIN, surface, approver)
    assert result.status == "success", result
    assert approver.asked == []
    assert surface.performed[0].value == "hunter2-pw"
    assert surface.performed[0].secret_ref == "password"
    assert "hunter2" not in log_text
    lines = [json.loads(x) for x in log_text.splitlines()]
    assert not [x for x in lines if x["type"].startswith("approval")]


def test_denied_sensitive_fill_fails_cleanly(tmp_path):
    surface = AppSurface(["App | Login", "App | Home", "App | Done"])
    result, _ = _run(
        tmp_path,
        _cap(),
        PII,
        surface,
        operant.application.approval.ScriptedApprover([False]),
        params=SSN,
    )
    assert result.status == "failure"
    assert result.failure.failure_class == "approval_denied"
    assert result.failure.at_edge == "e1" and surface.performed == []


def test_unanswered_console_approval_times_out(tmp_path):
    broker = operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )
    surface = AppSurface(["App | Login", "App | Home", "App | Done"])
    result, _ = _run(
        tmp_path,
        _cap(),
        PII,
        surface,
        operant.application.approval.BrokerApprover(broker, timeout_s=0.05),
        params=SSN,
    )
    assert result.status == "failure"
    assert result.failure.failure_class == "approval_denied"
    assert "timeout" in result.failure.observed


def test_no_approver_means_deny(tmp_path):
    surface = AppSurface(["App | Login", "App | Home", "App | Done"])
    result, _ = _run(tmp_path, _cap(), PII, surface, params=SSN)
    assert result.status == "failure"
    assert "denied-by-default" in result.failure.observed


def test_remembered_approval_spans_replays(tmp_path):
    inner = operant.application.approval.ScriptedApprover(
        [approval.ApprovalDecision(approved=True, remember="process")]
    )
    approver = operant.application.approval.RememberingApprover(inner, cache={})
    for i in range(2):
        result, _ = _run(
            tmp_path,
            _cap(),
            PII,
            AppSurface(["App | Login", "App | Home", "App | Done"]),
            approver,
            params=SSN,
            run=f"run{i}",
        )
        assert result.status == "success"
    assert len(inner.asked) == 1


NAV = [
    _edge("e1", "login", "home", {"kind": "click"}, "Log In", role="button"),
    _edge("e2", "home", "done", {"kind": "press", "key": "Tab"}),
]


def test_sensitive_output_is_redacted_in_the_log_but_returned(tmp_path):
    cap = _cap(
        extract_at_node="home",
        extract=[
            artifact.ExtractSpec(
                output="balance", pattern=r"Balance: \$([0-9.]+)"
            )
        ],
        outputs={"balance": artifact.OutField(description="b")},
    )
    result, log_text = _run(
        tmp_path,
        cap,
        NAV,
        AppSurface(["App | Login", "App | Home", "App | Done"]),
        operant.application.approval.ScriptedApprover([]),
    )
    assert result.status == "success"
    assert result.outputs == {"balance": "42.00"}
    assert "42.00" not in log_text
    extracted = next(
        json.loads(x) for x in log_text.splitlines() if '"outputs_extracted"' in x
    )
    assert extracted["outputs"] == {"balance": "[REDACTED]"}


def test_dataflow_within_one_app_is_a_sensitive_fill_not_an_export(tmp_path):
    cap = _cap(
        extract_at_node="home",
        extract=[
            artifact.ExtractSpec(
                output="balance", pattern=r"Balance: \$([0-9.]+)"
            )
        ],
    )
    edges = [
        NAV[0],
        _edge(
            "e2",
            "home",
            "done",
            {"kind": "fill", "value": {"from_output": "balance"}},
            "Message",
            role="text_area",
        ),
    ]
    approver = operant.application.approval.ScriptedApprover([True])
    result, _ = _run(
        tmp_path,
        cap,
        edges,
        AppSurface(["App | Login", "App | Home", "App | Done"]),
        approver,
    )
    assert result.status == "success"
    assert [r.kind for r in approver.asked] == ["sensitive_fill"]
    assert approver.asked[0].details["data_class"] == "financial"


def test_value_from_another_vendor_is_an_export(tmp_path):
    cap = _cap(vendor="whatsapp", start_node="home")
    edges = [
        _edge(
            "e1",
            "home",
            "done",
            {"kind": "fill", "value": {"from_output": "balance"}},
            "Message",
            role="text_area",
        )
    ]
    approver = operant.application.approval.ScriptedApprover([True])
    result, _ = _run(
        tmp_path,
        cap,
        edges,
        AppSurface(["App | Home", "App | Done"], app="WhatsApp"),
        approver,
        params={"balance": "42.00"},
        origins={
            "balance": operant.application.replay.options.OutputOrigin(
                vendor_id="parabank", data_class="financial"
            )
        },
    )
    assert result.status == "success", result
    assert [r.kind for r in approver.asked] == ["sensitive_export"]
    assert approver.asked[0].details["from_app"] == "parabank"
    assert approver.asked[0].details["to_app"] == "WhatsApp"
    assert "42.00" not in repr(approver.asked[0])


def test_harmless_value_from_another_vendor_is_not_gated(tmp_path):
    cap = _cap(vendor="whatsapp", start_node="home")
    edges = [
        _edge(
            "e1",
            "home",
            "done",
            {"kind": "fill", "value": {"from_output": "greeting"}},
            "Message",
            role="text_area",
        )
    ]
    approver = operant.application.approval.ScriptedApprover([])
    result, _ = _run(
        tmp_path,
        cap,
        edges,
        AppSurface(["App | Home", "App | Done"]),
        approver,
        params={"greeting": "hello"},
        origins={
            "greeting": operant.application.replay.options.OutputOrigin(
                vendor_id="parabank", data_class="none"
            )
        },
    )
    assert result.status == "success" and approver.asked == []


def test_mutating_click_needs_approval(tmp_path):
    edges = [
        NAV[0],
        _edge("e2", "home", "done", {"kind": "click"}, "Send", role="button"),
    ]
    approver = operant.application.approval.ScriptedApprover([True])
    surface = AppSurface(["App | Login", "App | Home", "App | Done"])
    result, _ = _run(tmp_path, _cap(), edges, surface, approver)
    assert result.status == "success"
    assert [r.kind for r in approver.asked] == ["mutating"]
    assert surface.performed[-1].target_text == "Send"


def test_enter_with_a_send_button_on_screen_is_mutating(tmp_path):
    edges = [
        NAV[0],
        _edge("e2", "home", "done", {"kind": "press", "key": "Enter"}),
    ]
    approver = operant.application.approval.ScriptedApprover([True])
    result, _ = _run(
        tmp_path,
        _cap(),
        edges,
        AppSurface(["App | Login", "App | Home", "App | Done"]),
        approver,
    )
    assert result.status == "success"
    assert [r.kind for r in approver.asked] == ["mutating"]
    assert "Enter" in approver.asked[0].summary
    assert "Send" in approver.asked[0].summary
