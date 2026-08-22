"""
Discovery-loop tests for goal-native parameters and clarifying questions,
driven by a scripted LLM and fake surfaces - no live app, no real model, no
monkeypatching.
"""

import json
import pathlib
import re
from typing import List, Optional

import operant.adapters.secrets.env as env
import operant.application.approval
import operant.application.capabilities
import operant.application.discovery.config as config
import operant.application.discovery.loop as loop
import operant.application.escalation
import operant.domain.models.digest as digest
import operant.domain.models.graph as mggraph
import operant.domain.profile as dpprofil
import operant.domain.redaction as redact
import operant.domain.secrets as odsec
import operant.infra.evidence.run_log as run_log
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as graphs
import tests.support.llm as llm
import tests.support.surfaces as surfaces

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

SECRETS = {"PARABANK_USERNAME": "john", "PARABANK_PASSWORD": "demo-pw-1"}


def _profile() -> dpprofil.AppProfile:
    raw = (REPO_ROOT / "policies" / "parabank.json").read_text()
    return dpprofil.AppProfile.model_validate(json.loads(raw))


def _control(ref: str, role: str, name: str, label: str = "") -> digest.Control:
    return digest.Control(
        ref=ref,
        role=role,
        name=name,
        label=label,
        path="p",
        box=digest.Box(0.1, 0.2, 0.2, 0.05),
    )


# #############################################################################
# FakeSurface
# #############################################################################


class FakeSurface:
    """
    Serve login -> overview; records performed actions.
    """

    def __init__(self) -> None:
        self.performed = []
        self._stage = "login"

    def snapshot(self) -> digest.ScreenDigest:
        if self._stage == "login":
            return digest.ScreenDigest(
                app="Chrome",
                window_title="ParaBank | Welcome",
                text="Customer Login",
                controls=(_control("c0", "link", "13344"),),
            )
        return digest.ScreenDigest(
            app="Chrome",
            window_title="ParaBank | Account",
            text="Balance: $10.00",
            controls=(),
        )

    def perform(self, action, *, approval=None) -> object:
        self.performed.append(action)
        if action.kind == "click":
            self._stage = "detail"
        return None

    def screenshot(self, path: pathlib.Path) -> bool:
        return False


# #############################################################################
# ScriptedClarifier
# #############################################################################


class ScriptedClarifier:

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.asked: List[str] = []

    def ask(self, question: str, *, run_id: str) -> str:
        self.asked.append(question)
        return self.answer


def _deps(tmp_path: pathlib.Path, surface, calls) -> loop.DiscoveryDeps:
    return loop.DiscoveryDeps(
        surface=surface,
        broker=operant.application.escalation.ControlBroker(
            start_human_capture=lambda cb: None,
            stop_human_capture=lambda: None,
            on_transition=lambda a, b, d: None,
        ),
        log=run_log.RunLog(tmp_path, "disc", redact.Redactor(), echo=False),
        llm=llm.scripted(calls),
        secret_store=env.EnvSecretStore(SECRETS),
        model_name="scripted",
        retry_base_delay_s=0.0,
    )


def _run(
    tmp_path: pathlib.Path,
    calls,
    *,
    clarifier=None,
    approver=None,
    surface=None,
    credential_requester=None,
):
    surface = surface if surface is not None else FakeSurface()
    deps = _deps(tmp_path, surface, calls)
    cfg = config.DiscoveryConfig(
        goal="read the balance of account 13344",
        capability_id="cap",
        capability_name="cap",
        inputs={},
        profile=_profile(),
        tenant="tenant-a",
        screenshots=False,
        clarifier=clarifier,
        approver=approver,
        credential_requester=credential_requester,
    )
    result = loop.run_discovery(cfg, deps)
    log_text = (tmp_path / "disc" / "run-log.jsonl").read_text()
    return result, surface, deps, log_text


HAPPY_TAIL = [
    ("act", {"action": "click", "ref": "c0", "intent": "open account 13344"}),
    ("extract", {"name": "balance", "pattern": r"Balance: (\$[\d.]+)"}),
    ("goal_complete", {"summary": "done"}),
]


def test_agent_declares_its_own_input(tmp_path: pathlib.Path) -> None:
    result, _, _, _ = _run(
        tmp_path,
        [
            ("declare_input", {"name": "accountId", "value": "13344"}),
            *HAPPY_TAIL,
        ],
    )
    assert isinstance(result, config.DiscoveryResult), result
    assert "accountId" in result.recording.inputs
    cap, _ = operant.application.capabilities.commit_recording(
        result.recording,
        graph_store=graphs.FileGraphRepository(tmp_path / "graphs"),
        artifact_store=artifact.FileArtifactRepository(tmp_path / "artifacts"),
    )
    assert "accountId" in cap.inputs


def test_clarify_invokes_channel_and_feeds_answer(tmp_path: pathlib.Path) -> None:
    clarifier = ScriptedClarifier("13344")
    result, _, _, _ = _run(
        tmp_path,
        [
            ("clarify", {"question": "Which account number?"}),
            ("declare_input", {"name": "accountId", "value": "13344"}),
            *HAPPY_TAIL,
        ],
        clarifier=clarifier,
    )
    assert clarifier.asked == ["Which account number?"]
    assert isinstance(result, config.DiscoveryResult)
    assert "accountId" in result.recording.inputs


def test_clarify_without_channel_does_not_crash(tmp_path: pathlib.Path) -> None:
    result, _, _, _ = _run(
        tmp_path,
        [
            ("clarify", {"question": "Which account?"}),
            ("declare_input", {"name": "accountId", "value": "13344"}),
            *HAPPY_TAIL,
        ],
    )
    assert isinstance(result, config.DiscoveryResult)


# #############################################################################
# ParaBankSurface
# #############################################################################


class ParaBankSurface(surfaces.GatedFakeSurface):
    """
    Policy-enforcing ParaBank: login (with a password field) -> account.
    """

    def __init__(self, policy) -> None:
        super().__init__(policy)
        self.stage = "login"

    def snapshot(self) -> digest.ScreenDigest:
        if self.stage == "login":
            return digest.ScreenDigest(
                app="Google Chrome",
                window_title="ParaBank | Welcome",
                text="Customer Login",
                controls=(
                    _control("c0", "link", "13344"),
                    _control("pw", "text_field", "", label="Password"),
                ),
            )
        return digest.ScreenDigest(
            app="Google Chrome",
            window_title="ParaBank | Account",
            text="Balance: $10.00",
            controls=(),
        )

    def apply(self, action) -> None:
        if action.kind == "click":
            self.stage = "detail"


def _tool_replies(deps: loop.DiscoveryDeps) -> List[str]:
    scripted = deps.llm
    assert isinstance(scripted, llm.ScriptedLlm)
    last = scripted.seen[-1]
    return [
        m.content for m in last if m.role == "tool" and isinstance(m.content, str)
    ]


def _prompt_dump(deps: loop.DiscoveryDeps) -> str:
    scripted = deps.llm
    assert isinstance(scripted, llm.ScriptedLlm)
    parts: List[str] = []
    for message in scripted.seen[-1]:
        if isinstance(message.content, str):
            parts.append(message.content)
        else:
            parts.extend(part.text for part in message.content)
        parts.extend(call.arguments for call in message.tool_calls)
    return "\n".join(parts)


def _run_gated(tmp_path: pathlib.Path, calls, approver):
    profile = _profile()
    return _run(
        tmp_path,
        calls,
        approver=approver,
        surface=ParaBankSurface(profile.policy),
    )


# #############################################################################
# ScriptedRequester
# #############################################################################


class ScriptedRequester:

    def __init__(self, grant: Optional[odsec.CredentialGrant]) -> None:
        self.grant = grant
        self.asked: List[str] = []

    def request(self, name, *, run_id, reason):
        self.asked.append(name)
        return self.grant


def test_credential_declaration_is_rejected(tmp_path: pathlib.Path) -> None:
    result, _, deps, _ = _run_gated(
        tmp_path,
        [
            (
                "declare_input",
                {
                    "name": "password",
                    "value": "demo-pw-1",
                    "data_class": "credential",
                },
            ),
            ("goal_complete", {"summary": "done"}),
        ],
        operant.application.approval.ScriptedApprover([]),
    )
    assert isinstance(result, config.DiscoveryResult), result
    assert "password" not in result.recording.inputs
    assert any("request_secret" in reply for reply in _tool_replies(deps))


def test_request_secret_typed_value_fills_via_placeholder(
    tmp_path: pathlib.Path,
) -> None:
    req = ScriptedRequester(odsec.CredentialGrant.typed("secret-code-9"))
    result, surface, _, log_text = _run(
        tmp_path,
        [
            ("request_secret", {"name": "logincode", "reason": "login"}),
            (
                "act",
                {
                    "action": "fill",
                    "ref": "pw",
                    "value": "$secret:logincode",
                    "intent": "enter the code",
                },
            ),
            ("goal_complete", {"summary": "done"}),
        ],
        surface=ParaBankSurface(_profile().policy),
        approver=operant.application.approval.ScriptedApprover([]),
        credential_requester=req,
    )
    assert isinstance(result, config.DiscoveryResult), result
    assert req.asked == ["logincode"]
    assert surface.performed[-1].value == "secret-code-9"
    assert surface.performed[-1].secret_ref == "logincode"
    assert "secret-code-9" not in log_text


def test_request_secret_sourced_locator_resolves_from_store(
    tmp_path: pathlib.Path,
) -> None:
    req = ScriptedRequester(
        odsec.CredentialGrant.sourced("env:PARABANK_PASSWORD")
    )
    result, surface, _, log_text = _run(
        tmp_path,
        [
            ("request_secret", {"name": "pw_ref", "reason": "login"}),
            (
                "act",
                {
                    "action": "fill",
                    "ref": "pw",
                    "value": "$secret:pw_ref",
                    "intent": "enter the password",
                },
            ),
            ("goal_complete", {"summary": "done"}),
        ],
        surface=ParaBankSurface(_profile().policy),
        approver=operant.application.approval.ScriptedApprover([]),
        credential_requester=req,
    )
    assert isinstance(result, config.DiscoveryResult), result
    assert surface.performed[-1].value == "demo-pw-1"
    assert "demo-pw-1" not in log_text


def test_secret_fill_runs_unattended_and_never_reaches_the_log(
    tmp_path: pathlib.Path,
) -> None:
    approver = operant.application.approval.ScriptedApprover([])
    result, surface, _, log_text = _run_gated(
        tmp_path,
        [
            (
                "act",
                {
                    "action": "fill",
                    "ref": "pw",
                    "value": "$secret:password",
                    "intent": "enter the password",
                },
            ),
            ("goal_complete", {"summary": "done"}),
        ],
        approver,
    )
    assert isinstance(result, config.DiscoveryResult), result
    assert approver.asked == []
    assert surface.performed[-1].value == "demo-pw-1"
    assert surface.performed[-1].secret_ref == "password"
    assert "demo-pw-1" not in log_text
    recorded = result.recording.edges[-1].action.value
    assert recorded is not None and recorded.secret_ref == "password"


def test_denied_fill_tells_the_model_and_performs_nothing(
    tmp_path: pathlib.Path,
) -> None:
    result, surface, deps, log_text = _run_gated(
        tmp_path,
        [
            (
                "act",
                {
                    "action": "fill",
                    "ref": "pw",
                    "value": "guessed-pw",
                    "intent": "enter the password",
                },
            ),
            ("goal_complete", {"summary": "gave up on login"}),
        ],
        operant.application.approval.ScriptedApprover([False]),
    )
    assert isinstance(result, config.DiscoveryResult)
    assert [a.kind for a in surface.performed] == ["launch"]
    assert any(
        reply.startswith("DENIED by human (sensitive_fill)")
        for reply in _tool_replies(deps)
    )
    assert '"policy_blocked"' in log_text


def test_declared_sensitive_inputs_are_classified_and_redacted(
    tmp_path: pathlib.Path,
) -> None:
    result, _, deps, log_text = _run_gated(
        tmp_path,
        [
            (
                "declare_input",
                {"name": "ssn", "value": "123-45-6789", "data_class": "pii"},
            ),
            ("act", {"action": "click", "ref": "c0", "intent": "open account"}),
            ("goal_complete", {"summary": "done"}),
        ],
        operant.application.approval.ScriptedApprover([]),
    )
    assert isinstance(result, config.DiscoveryResult), result
    assert result.recording.inputs["ssn"].data_class == "pii"
    declared = [
        json.loads(x) for x in log_text.splitlines() if '"input_declared"' in x
    ]
    assert [d["value"] for d in declared] == ["[REDACTED]"]
    prompt = _prompt_dump(deps)
    assert "123-45-6789" in prompt


def _run_with_known_graph(tmp_path, known):
    surface = FakeSurface()
    deps = _deps(tmp_path, surface, [("goal_complete", {"summary": "done"})])
    cfg = config.DiscoveryConfig(
        goal="read the balance of the savings account",
        capability_id="cap",
        capability_name="cap",
        inputs={},
        profile=_profile(),
        tenant="tenant-a",
        screenshots=False,
        known_graph=known,
    )
    loop.run_discovery(cfg, deps)
    return deps


def _welcome_graph() -> mggraph.AppGraph:
    return mggraph.AppGraph(
        vendor_id="parabank",
        nodes=[
            mggraph.Node(
                id="welcome",
                description="login",
                checks=[
                    mggraph.TitleMatches(pattern=re.escape("ParaBank | Welcome"))
                ],
            )
        ],
        edges=[],
    )


def test_recognized_state_surfaced_when_a_known_graph_matches(tmp_path):
    deps = _run_with_known_graph(tmp_path, _welcome_graph())
    # The distinctive injected observation line, not the prompt's mention.
    assert 'matches a mapped state "ParaBank | Welcome"' in _prompt_dump(deps)


def test_no_recognition_line_without_a_known_graph(tmp_path):
    deps = _run_with_known_graph(tmp_path, None)
    assert "matches a mapped state" not in _prompt_dump(deps)


def test_recognized_state_lists_known_next_steps(tmp_path):
    kg = mggraph.AppGraph(
        vendor_id="parabank",
        nodes=[
            mggraph.Node(
                id="welcome",
                description="login",
                checks=[
                    mggraph.TitleMatches(pattern=re.escape("ParaBank | Welcome"))
                ],
            ),
            mggraph.Node(
                id="overview",
                description="overview",
                checks=[mggraph.TitleMatches(pattern="Accounts Overview")],
            ),
        ],
        edges=[
            mggraph.Edge.model_validate(
                {
                    "id": "e1",
                    "from": "welcome",
                    "to": "overview",
                    "description": "log in with username and password",
                    "action": {"kind": "click"},
                }
            )
        ],
    )
    prompt = _prompt_dump(_run_with_known_graph(tmp_path, kg))
    assert "Actions already mapped from here" in prompt
    assert "log in with username and password" in prompt


def test_recognized_state_is_logged_as_evidence(tmp_path):
    _run_with_known_graph(tmp_path, _welcome_graph())
    log_lines = (tmp_path / "disc" / "run-log.jsonl").read_text().splitlines()
    events = [json.loads(x) for x in log_lines]
    localized = [e for e in events if e.get("type") == "localized"]
    assert localized, "recognition should emit a localized event"
    assert any("discovery recognized" in e.get("summary", "") for e in localized)
