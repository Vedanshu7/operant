"""
Behavioral eval harness: run discovery against the REAL model over synthetic
screens, then assert on the tool-call trace.

These evals check prompt QUALITY - does a real model follow the rules the
system prompt states - as opposed to the unit tests, which pin the
MECHANISM with a scripted model. They are app-agnostic: each scenario is
a fake surface plus a goal, so a rule that regresses on a generic profile
(not just ParaBank) is caught. Opt-in and gated behind an API model, they
never run in the normal unit suite.

Import as:

import tests.evals.harness as harness
"""

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
from typing import FrozenSet, List, Optional, Tuple

import operant.application.discovery.config as config
import operant.application.discovery.loop as loop
import operant.application.escalation as escal
import operant.domain.approval as daapprov
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.llm as mlllm
import operant.domain.policy as policy
import operant.domain.profile as profile
import operant.domain.redaction as redact
import operant.domain.secrets as odsec
import operant.infra.evidence.run_log as run_log
import operant.ports.llm as plllm
import operant.ports.secrets as pssecret

# #############################################################################
# RecordingLlm
# #############################################################################


class RecordingLlm:
    """
    Wrap a real client and record every tool call it emits, in order.
    """

    def __init__(self, inner: plllm.LlmClient) -> None:
        self._inner = inner
        self.turns: List[Tuple[mlllm.ToolCall, ...]] = []

    def complete(
        self,
        messages: collections.abc.Sequence[mlllm.ChatMessage],
        *,
        tools: collections.abc.Sequence[mlllm.ToolSchema],
    ) -> mlllm.LlmTurn:
        turn = self._inner.complete(messages, tools=tools)
        self.turns.append(turn.tool_calls)
        return turn

    @property
    def calls(self) -> List[mlllm.ToolCall]:
        """
        The full flat sequence of tool calls across every turn.
        """
        return [call for turn in self.turns for call in turn]

    def names(self) -> List[str]:
        """
        Just the tool names, in the order the model called them.
        """
        return [call.name for call in self.calls]


# #############################################################################
# FakeEvalSurface
# #############################################################################


class FakeEvalSurface:
    """
    Serve a fixed sequence of screens; advance on click/launch.
    """

    def __init__(
        self,
        screens: collections.abc.Sequence[digest.ScreenDigest],
        *,
        advance_on: FrozenSet[str] = frozenset({"click", "launch"}),
    ) -> None:
        self._screens = list(screens)
        self._advance_on = advance_on
        self._index = 0
        self.performed: List[object] = []

    def snapshot(self) -> digest.ScreenDigest:
        return self._screens[min(self._index, len(self._screens) - 1)]

    def perform(
        self, action: object, *, approval: Optional[str] = None
    ) -> object:
        self.performed.append(action)
        kind = getattr(action, "kind", "")
        if kind in self._advance_on and self._index < len(self._screens) - 1:
            self._index += 1
        return None

    def retarget(self, app_name: str, pattern: str) -> Tuple[str, str]:
        return ("", "")

    def target_text_for(self, ref: Optional[str]) -> str:
        screen = self.snapshot()
        control = next((c for c in screen.controls if c.ref == ref), None)
        if control is None:
            return ""
        return " | ".join(x for x in (control.name, control.label) if x)

    def screenshot(self, path: pathlib.Path) -> bool:
        return False


# #############################################################################
# _ApproveAll
# #############################################################################


class _ApproveAll:

    def ask(self, request: daapprov.ApprovalRequest) -> daapprov.ApprovalDecision:
        return daapprov.ApprovalDecision(approved=True)


# #############################################################################
# _CannedClarifier
# #############################################################################


class _CannedClarifier:

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.asked: List[str] = []

    def ask(self, question: str, *, run_id: str) -> str:
        self.asked.append(question)
        return self.answer


# #############################################################################
# _CannedCredentials
# #############################################################################


class _CannedCredentials:

    def __init__(self) -> None:
        self.requested: List[str] = []

    def request(
        self, name: str, *, run_id: str, reason: str
    ) -> odsec.CredentialGrant:
        self.requested.append(name)
        return odsec.CredentialGrant.typed("eval-value")


def _box() -> digest.Box:
    return digest.Box(x=0.1, y=0.1, w=0.2, h=0.05)


def control(
    role: str, name: str, *, ref: str = "", label: str = ""
) -> digest.Control:
    """
    Build a control for a synthetic screen.
    """
    return digest.Control(
        ref=ref or name.lower().replace(" ", "-") or role,
        role=role,
        name=name,
        label=label,
        path=f"content>{role}",
        box=_box(),
    )


def screen(
    title: str, *controls: digest.Control, text: str = ""
) -> digest.ScreenDigest:
    """
    Build a synthetic screen digest.
    """
    return digest.ScreenDigest(
        app="Chrome", window_title=title, text=text or title, controls=controls
    )


_POLICY_KINDS = ["launch", "click", "fill", "press", "select", "scroll"]


def _profile() -> profile.AppProfile:
    return profile.AppProfile(
        vendor_id="evalapp",
        app_name="Google Chrome",
        window_title_pattern=".*",
        policy=policy.Policy(
            id="evalapp",
            allowed_apps=["Google Chrome"],
            allowed_url_patterns=[".*"],
            allowed_action_kinds=_POLICY_KINDS,
            mutating_control_patterns=["transfer", "send", "pay"],
        ),
        tenants={
            "t": artifact.TenantBinding(
                base_url="http://localhost:8081", secret_refs={}
            )
        },
        default_tenant="t",
    )


# #############################################################################
# EvalRun
# #############################################################################


@dataclasses.dataclass
class EvalRun:
    """
    The result of one eval scenario: the trace and the terminal result.
    """

    llm: RecordingLlm
    result: object
    clarifier: _CannedClarifier
    credentials: _CannedCredentials
    surface: FakeEvalSurface


def run_scenario(
    tmp_path: pathlib.Path,
    inner_llm: plllm.LlmClient,
    secret_store: pssecret.SecretStore,
    *,
    goal: str,
    screens: collections.abc.Sequence[digest.ScreenDigest],
    known_graph: Optional[graph.AppGraph] = None,
    max_turns: int = 4,
    clarify_answer: str = "https://example.test/app",
) -> EvalRun:
    """
    Run one discovery scenario against the real model over ``screens``.
    """
    recording = RecordingLlm(inner_llm)
    surface = FakeEvalSurface(screens)
    clarifier = _CannedClarifier(clarify_answer)
    credentials = _CannedCredentials()
    deps = loop.DiscoveryDeps(
        surface=surface,
        broker=escal.ControlBroker(
            start_human_capture=lambda cb: None,
            stop_human_capture=lambda: None,
            on_transition=lambda a, b, d: None,
        ),
        log=run_log.RunLog(tmp_path, "eval", redact.Redactor(), echo=False),
        llm=recording,
        secret_store=secret_store,
        model_name="eval",
        retry_base_delay_s=0.0,
    )
    cfg = config.DiscoveryConfig(
        goal=goal,
        capability_id="eval",
        capability_name="eval",
        inputs={},
        profile=_profile(),
        tenant="t",
        max_turns=max_turns,
        screenshots=False,
        clarifier=clarifier,
        approver=_ApproveAll(),
        credential_requester=credentials,
        known_graph=known_graph,
    )
    result = loop.run_discovery(cfg, deps)
    return EvalRun(recording, result, clarifier, credentials, surface)
