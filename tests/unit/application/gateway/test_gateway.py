import dataclasses
from typing import Dict, List, Set, Tuple

import pytest

import operant.application.gateway.dispatcher as dispat
import operant.application.gateway.guard as guard
import operant.application.gateway.registry as grregist
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.tools as tools
import operant.domain.policy as policy

# #############################################################################
# ScriptedTool
# #############################################################################


@dataclasses.dataclass
class ScriptedTool:
    spec: tools.ToolSpec
    result: tools.ToolResult
    health_status: str = "ok"
    calls: List[str] = dataclasses.field(default_factory=list)

    def health(self) -> tools.ToolHealth:
        return tools.ToolHealth(status=self.health_status, reason="probe")

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        self.calls.append(action.kind)
        return self.result


def make(
    name: str, serves: Set[str], result: tools.ToolResult, health: str = "ok"
) -> ScriptedTool:
    return ScriptedTool(
        spec=tools.ToolSpec(name=name, version="1", serves=frozenset(serves)),
        result=result,
        health_status=health,
    )


def setup(
    scripted: List[ScriptedTool], chains: Dict[str, List[str]], **dispatcher_kw
) -> Tuple[dispat.Dispatcher, List[dict]]:
    registry = grregist.ToolRegistry()
    for tool in scripted:
        registry.register(tool)
    config = grregist.GatewayConfig(chains=chains)
    registry.validate(config)
    events: List[dict] = []
    dispatcher = dispat.Dispatcher(
        registry, config, on_event=events.append, **dispatcher_kw
    )
    return dispatcher, events


CTX = tools.ExecutionContext(session=None)


def test_first_ok_tool_wins_and_is_journaled():
    a = make("a", {"fill"}, tools.ToolResult(status="ok", verified=True))
    b = make("b", {"fill"}, tools.ToolResult(status="ok", verified=True))
    dispatcher, events = setup([a, b], {"fill": ["a", "b"]})
    outcome = dispatcher.dispatch(
        actions.SurfaceAction(kind="fill", ref="c1", value="x"), CTX
    )
    assert outcome.tool == "a"
    assert b.calls == []
    assert [e["tool"] for e in events if e["type"] == "gateway_action"] == ["a"]


def test_failed_tool_falls_through_to_next():
    a = make(
        "a", {"fill"}, tools.ToolResult(status="failed", reason="write no-op")
    )
    b = make("b", {"fill"}, tools.ToolResult(status="ok", verified=True))
    dispatcher, _events = setup([a, b], {"fill": ["a", "b"]})
    outcome = dispatcher.dispatch(
        actions.SurfaceAction(kind="fill", ref="c1", value="x"), CTX
    )
    assert outcome.tool == "b"
    assert [attempt.status for attempt in outcome.attempts] == ["failed", "ok"]


def test_crashing_tool_is_a_failed_attempt_not_a_dead_run():
    class CrashingTool(ScriptedTool):

        def execute(self, action, ctx):
            raise TypeError("expected (int, int) tuple or Element for target")

    a = CrashingTool(
        spec=tools.ToolSpec(name="a", version="1", serves=frozenset({"click"})),
        result=tools.ToolResult(status="ok"),
    )
    b = make("b", {"click"}, tools.ToolResult(status="ok", verified=True))
    dispatcher, _events = setup([a, b], {"click": ["a", "b"]})
    outcome = dispatcher.dispatch(
        actions.SurfaceAction(kind="click", ref="c1"), CTX
    )
    assert outcome.tool == "b"
    assert outcome.attempts[0].status == "failed"
    assert "TypeError" in (outcome.attempts[0].reason or "")


def test_unavailable_health_skips_tool_without_executing():
    a = make("a", {"fill"}, tools.ToolResult(status="ok"), health="unavailable")
    b = make("b", {"fill"}, tools.ToolResult(status="ok", verified=True))
    dispatcher, events = setup([a, b], {"fill": ["a", "b"]})
    outcome = dispatcher.dispatch(
        actions.SurfaceAction(kind="fill", ref="c1", value="x"), CTX
    )
    assert outcome.tool == "b"
    assert a.calls == []
    assert any(e["type"] == "gateway_skip" and e["tool"] == "a" for e in events)


def test_all_tools_failed_raises_with_attempt_detail():
    a = make("a", {"fill"}, tools.ToolResult(status="failed", reason="r1"))
    b = make("b", {"fill"}, tools.ToolResult(status="failed", reason="r2"))
    dispatcher, _ = setup([a, b], {"fill": ["a", "b"]})
    with pytest.raises(errors.AllToolsFailedError) as err:
        dispatcher.dispatch(
            actions.SurfaceAction(kind="fill", ref="c1", value="x"), CTX
        )
    assert [attempt.tool for attempt in err.value.attempts] == ["a", "b"]


def test_no_usable_tool_raises():
    a = make("a", {"fill"}, tools.ToolResult(status="ok"), health="unavailable")
    dispatcher, _ = setup([a], {"fill": ["a"]})
    with pytest.raises(errors.NoToolAvailableError):
        dispatcher.dispatch(
            actions.SurfaceAction(kind="fill", ref="c1", value="x"), CTX
        )


def test_unverified_ok_goes_through_shared_verifier():
    a = make("a", {"fill"}, tools.ToolResult(status="ok", verified=False))
    b = make("b", {"fill"}, tools.ToolResult(status="ok", verified=True))
    verdicts = iter([(False, "value still empty")])
    dispatcher, _ = setup(
        [a, b],
        {"fill": ["a", "b"]},
        verifiers={"fill": lambda action, ctx: next(verdicts)},
    )
    outcome = dispatcher.dispatch(
        actions.SurfaceAction(kind="fill", ref="c1", value="x"), CTX
    )
    # a reported ok but verification failed -> fell through to b
    assert outcome.tool == "b"
    assert outcome.attempts[0].status == "failed"
    assert "not verified" in outcome.attempts[0].reason


def test_sensitive_fill_skips_tools_that_leak_the_value():
    leaky = ScriptedTool(
        spec=tools.ToolSpec(
            name="clip",
            version="1",
            serves=frozenset({"fill"}),
            leaks_value=True,
        ),
        result=tools.ToolResult(status="ok", verified=True),
    )
    safe = make("ax", {"fill"}, tools.ToolResult(status="ok", verified=True))
    dispatcher, events = setup([leaky, safe], {"fill": ["clip", "ax"]})
    outcome = dispatcher.dispatch(
        actions.SurfaceAction(
            kind="fill", ref="c1", value="hunter2", data_class="credential"
        ),
        CTX,
    )
    assert outcome.tool == "ax" and leaky.calls == []
    assert outcome.attempts[0].status == "skipped_sensitive"
    assert any(
        e["type"] == "gateway_skip" and e["tool"] == "clip" for e in events
    )
    assert "hunter2" not in repr(events)
    plain = dispatcher.dispatch(
        actions.SurfaceAction(kind="fill", ref="c1", value="hello"), CTX
    )
    assert plain.tool == "clip"


def test_registry_rejects_chain_with_wrong_serves():
    registry = grregist.ToolRegistry()
    registry.register(make("a", {"click"}, tools.ToolResult(status="ok")))
    with pytest.raises(errors.ConfigError, match="does not serve"):
        registry.chain_for("fill", grregist.GatewayConfig(chains={"fill": ["a"]}))


POLICY = policy.Policy(
    id="t",
    allowed_apps=["Google Chrome"],
    allowed_url_patterns=["^http://localhost"],
    allowed_action_kinds=["launch", "click", "fill", "press"],
    mutating_control_patterns=["transfer"],
)


def digest_with(*controls: digest.Control) -> digest.ScreenDigest:
    return digest.ScreenDigest(
        app="Chrome", window_title="t", text="", controls=controls
    )


def button(ref: str, name: str) -> digest.Control:
    return digest.Control(
        ref=ref,
        role="button",
        name=name,
        label="",
        path="p",
        box=digest.Box(0, 0, 0.1, 0.1),
    )


def make_gateway(
    scripted: List[ScriptedTool], chains: Dict[str, List[str]]
) -> Tuple[guard.GuardedGateway, list]:
    dispatcher, _ = setup(scripted, chains)
    decisions: list = []
    gateway = guard.GuardedGateway(
        dispatcher, POLICY, on_decision=lambda d, a: decisions.append(d)
    )
    return gateway, decisions


def test_guard_withholds_mutating_action_until_the_nonce_comes_back():
    tool = make("a", {"click"}, tools.ToolResult(status="ok", verified=True))
    gateway, decisions = make_gateway([tool], {"click": ["a"], "observe": []})
    gateway._last_digest = digest_with(button("c1", "Transfer Funds"))
    with pytest.raises(errors.ApprovalRequiredError) as err:
        gateway.perform(actions.SurfaceAction(kind="click", ref="c1"), CTX)
    assert tool.calls == []
    assert err.value.request.kind == "mutating"
    assert decisions[-1].verdict == "needs_approval"
    gateway.perform(
        actions.SurfaceAction(kind="click", ref="c1"),
        CTX,
        approval=err.value.nonce,
    )
    assert tool.calls == ["click"]
    assert decisions[-1].allowed and "approved by human" in decisions[-1].reason


def test_nonce_is_single_use():
    tool = make("a", {"click"}, tools.ToolResult(status="ok", verified=True))
    gateway, _ = make_gateway([tool], {"click": ["a"], "observe": []})
    gateway._last_digest = digest_with(button("c1", "Transfer Funds"))
    action = actions.SurfaceAction(kind="click", ref="c1")
    with pytest.raises(errors.ApprovalRequiredError) as first:
        gateway.perform(action, CTX)
    gateway.perform(action, CTX, approval=first.value.nonce)
    with pytest.raises(errors.ApprovalRequiredError) as again:
        gateway.perform(action, CTX, approval=first.value.nonce)
    assert again.value.nonce != first.value.nonce
    assert tool.calls == ["click"]


def test_nonce_is_bound_to_the_question():
    tool = make("a", {"click"}, tools.ToolResult(status="ok", verified=True))
    gateway, _ = make_gateway([tool], {"click": ["a"], "observe": []})
    gateway._last_digest = digest_with(
        button("c1", "Transfer Funds"), button("c2", "Transfer Everything")
    )
    with pytest.raises(errors.ApprovalRequiredError) as err:
        gateway.perform(actions.SurfaceAction(kind="click", ref="c1"), CTX)
    with pytest.raises(errors.ApprovalRequiredError):
        gateway.perform(
            actions.SurfaceAction(kind="click", ref="c2"),
            CTX,
            approval=err.value.nonce,
        )
    assert tool.calls == []


def test_guard_classifies_a_sensitive_fill_from_the_digest_alone():
    tool = make("a", {"fill"}, tools.ToolResult(status="ok", verified=True))
    gateway, decisions = make_gateway([tool], {"fill": ["a"], "observe": []})
    gateway._last_digest = digest_with(
        digest.Control(
            ref="c1",
            role="text_field",
            name="",
            label="Password",
            path="p",
            box=digest.Box(0, 0, 0.1, 0.1),
        ),
    )
    with pytest.raises(errors.ApprovalRequiredError) as err:
        gateway.perform(
            actions.SurfaceAction(kind="fill", ref="c1", value="hunter2-pw"),
            CTX,
        )
    request = err.value.request
    assert request.kind == "sensitive_fill"
    assert request.details["data_class"] == "credential"
    assert request.app == "Chrome"
    assert "hunter2" not in decisions[-1].reason
    assert "hunter2" not in repr(request)
    assert tool.calls == []


def test_guard_denies_disallowed_kind_outright():
    tool = make("a", {"scroll"}, tools.ToolResult(status="ok", verified=True))
    gateway, decisions = make_gateway([tool], {"scroll": ["a"], "observe": []})
    with pytest.raises(errors.PolicyViolationError):
        gateway.perform(
            actions.SurfaceAction(kind="scroll", direction="down", amount=3),
            CTX,
        )
    assert decisions[-1].verdict == "deny" and tool.calls == []


def test_guard_observe_bypasses_action_allowlist_and_caches_digest():
    d = digest_with(button("c1", "ok"))
    observer = make(
        "obs",
        {"observe"},
        tools.ToolResult(status="ok", verified=True, digest=d),
    )
    gateway, _ = make_gateway([observer], {"observe": ["obs"]})
    ctx = tools.ExecutionContext(session=None)
    got = gateway.observe(ctx)
    assert got is d
    assert gateway.last_digest is d
    assert ctx.digest is d
