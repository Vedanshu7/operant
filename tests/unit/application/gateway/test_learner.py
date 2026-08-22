import dataclasses
from typing import List

import operant.application.gateway.dispatcher as dispat
import operant.application.gateway.learner as gllearne
import operant.application.gateway.registry as grregist
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.tools as tools
import tests.support.ports as ports

# #############################################################################
# ScriptedTool
# #############################################################################


@dataclasses.dataclass
class ScriptedTool:
    spec: tools.ToolSpec
    result: tools.ToolResult
    calls: List[str] = dataclasses.field(default_factory=list)

    def health(self) -> tools.ToolHealth:
        return tools.ToolHealth("ok")

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        self.calls.append(action.kind)
        return self.result


def tool(name: str, ok: bool) -> ScriptedTool:
    return ScriptedTool(
        spec=tools.ToolSpec(name=name, version="1", serves=frozenset({"fill"})),
        result=tools.ToolResult(
            status="ok" if ok else "failed",
            verified=True,
            reason="" if ok else "no-op",
        ),
    )


DIGEST = digest.ScreenDigest(
    app="Google Chrome",
    window_title="ParaBank | Welcome - Google Chrome",
    text="",
    controls=(
        digest.Control(
            ref="c0",
            role="text_field",
            name="",
            label="Username",
            path="p",
            box=digest.Box(0, 0, 0.1, 0.1),
        ),
    ),
)


def test_signature_generalizes_across_records():
    a = actions.SurfaceAction(
        kind="fill",
        ref="c0",
        value="13344",
        target_text="text_field | Username",
    )
    b = actions.SurfaceAction(
        kind="fill",
        ref="c0",
        value="99999",
        target_text="text_field | Username",
    )
    # Same page/kind/role -> same signature despite different values and
    # title digits.
    s1 = gllearne.signature(
        a, "Google Chrome", "ParaBank | Account 13344 - Google Chrome"
    )
    s2 = gllearne.signature(
        b, "Google Chrome", "ParaBank | Account 99999 - Google Chrome"
    )
    assert s1 == s2


def test_learner_records_and_reorders():
    store = ports.FakePreferenceStore()
    learner = gllearne.ToolLearner(store)
    sig = "sig-1"
    assert learner.order_chain(sig, ["a", "b", "c"]) == ["a", "b", "c"]
    assert learner.record(sig, "c") is True
    assert learner.record(sig, "c") is False  # no change second time
    assert learner.order_chain(sig, ["a", "b", "c"]) == ["c", "a", "b"]
    # Persisted through the store.
    reloaded = gllearne.ToolLearner(store)
    assert reloaded.preferred(sig) == "c"


def test_dispatcher_learns_winner_then_leads_with_it():
    a = tool("a", ok=False)  # first tool fails
    b = tool("b", ok=True)  # second tool wins
    registry = grregist.ToolRegistry()
    registry.register(a)
    registry.register(b)
    config = grregist.GatewayConfig(chains={"fill": ["a", "b"]})
    learner = gllearne.ToolLearner(ports.FakePreferenceStore())
    events: List[dict] = []
    dispatcher = dispat.Dispatcher(
        registry,
        config,
        on_event=events.append,
        learner=learner,
        signature_of=lambda action, digest_: gllearne.signature(
            action, "Google Chrome", DIGEST.window_title
        ),
    )
    ctx = tools.ExecutionContext(session=None, digest=DIGEST)
    act = actions.SurfaceAction(
        kind="fill", ref="c0", value="x", target_text="text_field | Username"
    )
    # First run: explores a (fail) then b (win); learns b.
    out1 = dispatcher.dispatch(act, ctx)
    assert out1.tool == "b"
    assert a.calls == ["fill"]
    assert any(
        e["type"] == "gateway_learned" and e["tool"] == "b" for e in events
    )
    # Second run: b leads the chain, a is never tried.
    a.calls.clear()
    out2 = dispatcher.dispatch(act, ctx)
    assert out2.tool == "b"
    assert a.calls == []
