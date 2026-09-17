import dataclasses
from typing import List

import operant.application.gateway.dispatcher as dispat
import operant.application.gateway.learner as gllearne
import operant.application.gateway.registry as grregist
import operant.domain.events as odevents
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


def _screen(title: str, control: digest.Control) -> digest.ScreenDigest:
    return digest.ScreenDigest(
        app="Google Chrome", window_title=title, text="", controls=(control,)
    )


def _link(name: str) -> digest.Control:
    return digest.Control(
        ref="c1",
        role="link",
        name=name,
        label="",
        path="p",
        box=digest.Box(0, 0, 0.1, 0.1),
    )


def test_signature_generalizes_across_records():
    a = actions.SurfaceAction(kind="click", ref="c1", target_text="open 13344")
    b = actions.SurfaceAction(kind="click", ref="c1", target_text="open 99999")
    # Same page, kind and kind of target -> one signature, whatever the
    # record or the model's wording.
    s1 = gllearne.signature(
        a,
        "Google Chrome",
        _screen("Bank | Account 13344 - Chrome", _link("13344")),
    )
    s2 = gllearne.signature(
        b,
        "Google Chrome",
        _screen("Bank | Account 99999 - Chrome", _link("99999")),
    )
    assert s1 == s2 == "Google Chrome::bank::click::link:#"


def test_signature_never_holds_the_models_wording():
    point = actions.SurfaceAction(
        kind="click", x=0.5, y=0.5, target_text="click on the password field"
    )
    sig = gllearne.signature(point, "", DIGEST)
    assert sig == "Google Chrome::parabank::click::point"


def test_an_unknown_app_is_never_learned():
    learner = gllearne.ToolLearner(ports.FakePreferenceStore())
    sig = gllearne.signature(
        actions.SurfaceAction(kind="press", key="Tab"), "", None
    )
    assert sig.startswith("::")
    assert learner.record(sig, "keys") is False
    assert learner.preferred(sig) is None


def test_learner_orders_by_success_rate():
    store = ports.FakePreferenceStore()
    learner = gllearne.ToolLearner(store)
    sig = "app::page::fill::text_field:username"
    assert learner.order_chain(sig, ["a", "b", "c"]) == ["a", "b", "c"]
    assert learner.record(sig, "c") is True
    # The leader has not changed.
    assert learner.record(sig, "c") is False
    assert learner.order_chain(sig, ["a", "b", "c"]) == ["c", "a", "b"]
    # One failure puts a tool behind the untried ones.
    learner.record(sig, "a", ok=False)
    assert learner.order_chain(sig, ["a", "b", "c"]) == ["c", "b", "a"]
    # Persisted through the store.
    reloaded = gllearne.ToolLearner(store)
    assert reloaded.preferred(sig) == "c"


def test_dispatcher_learns_winner_then_leads_with_it():
    # The first tool fails and the second wins.
    a = tool("a", ok=False)
    b = tool("b", ok=True)
    registry = grregist.ToolRegistry()
    registry.register(a)
    registry.register(b)
    config = grregist.GatewayConfig(chains={"fill": ["a", "b"]})
    learner = gllearne.ToolLearner(ports.FakePreferenceStore())
    events: List[odevents.GatewayEvent] = []
    dispatcher = dispat.Dispatcher(
        registry,
        config,
        on_event=events.append,
        learner=learner,
        signature_of=lambda action, digest_: gllearne.signature(
            action, "Google Chrome", digest_
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
    assert any(e.type == "gateway_learned" and e.tool == "b" for e in events)
    # Second run: b leads the chain, a is never tried.
    a.calls.clear()
    out2 = dispatcher.dispatch(act, ctx)
    assert out2.tool == "b"
    assert a.calls == []
