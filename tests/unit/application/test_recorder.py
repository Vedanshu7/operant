"""
Recorder: node synthesis, parameterisation, and capability-scoped extraction -
the rules that make a recorded flow replayable for OTHER inputs.
"""

import operant.application.recorder.recording
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import tests.support.recording


def _screen(title: str, *controls: digest.Control) -> digest.ScreenDigest:
    return digest.ScreenDigest(
        app="Chrome", window_title=title, text="", controls=controls
    )


def _ctl(role: str, name: str, path: str) -> digest.Control:
    return digest.Control(
        ref=name,
        role=role,
        name=name,
        label="",
        path=path,
        box=digest.Box(0.1, 0.1, 0.2, 0.05),
    )


def test_node_stores_content_fingerprint() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start(
        "Welcome", _screen("Welcome", _ctl("button", "Log In", "form>button"))
    )
    node = next(iter(recorder.nodes.values()))
    assert node.fingerprint == ["button|log in||form>button"]


def test_same_title_but_divergent_content_is_a_new_node() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    login = _screen(
        "Welcome",
        _ctl("text_field", "Username", "form>text_field"),
        _ctl("button", "Log In", "form>button"),
    )
    overview = _screen(
        "Welcome",
        _ctl("link", "Accounts Overview", "menu>link"),
        _ctl("link", "Log Out", "menu>link"),
    )
    recorder.start("Welcome", login)
    # Same "Welcome" title, different content: must not collapse into one.
    recorder.record(
        action=graph.Action(kind="click"),
        target_control=None,
        description="log in",
        risk="safe",
        pre_title="Welcome",
        post_title="Welcome",
        screen=overview,
    )
    assert len(recorder.nodes) == 2
    assert (
        recorder.recorded[0].edge.from_node != recorder.recorded[0].edge.to_node
    )


def test_same_title_is_same_node_and_self_edge() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Overview - Acme - Google Chrome")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="fill", value=targets.Value(literal="x")),
        control=tests.support.recording.control("Field", "text_field"),
        description="fill field",
        pre="Overview - Acme - Google Chrome",
        post="Overview - Acme - Google Chrome",
    )
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Go"),
        description="go",
        pre="Overview - Acme - Google Chrome",
        post="Details - Acme - Google Chrome",
    )
    rec = tests.support.recording.build_recording(recorder, {}, {})
    assert len(rec.nodes) == 2
    assert rec.edges[0].from_node == rec.edges[0].to_node
    assert rec.edges[1].from_node != rec.edges[1].to_node


def test_input_values_become_params_in_value_and_description() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Search - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="fill", value=targets.Value(literal="13344")),
        control=tests.support.recording.control("Account", "text_field"),
        description="enter account 13344",
        pre="Search - Acme",
        post="Search - Acme",
    )
    rec = tests.support.recording.build_recording(
        recorder, {"accountId": "13344"}, {}
    )
    edge = rec.edges[0]
    assert edge.action.value == targets.Value(param="accountId")
    assert "{{accountId}}" in edge.description


def test_record_identifying_target_drops_non_parameterized_strategies() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Overview - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("13344"),
        description="open account 13344",
        pre="Overview - Acme",
        post="Activity - Acme",
    )
    rec = tests.support.recording.build_recording(
        recorder, {"accountId": "13344"}, {}
    )
    edge = rec.edges[0]
    assert edge.target is not None
    assert all(
        isinstance(s, targets.RoleStrategy) and "{{accountId}}" in s.name
        for s in edge.target.strategies
    )
    not_found = [
        o
        for o in rec.outcome_edges
        if o.handle.type == "business_outcome"
        and o.handle.outcome == "RECORD_NOT_FOUND"
    ]
    assert len(not_found) == 1
    assert not_found[0].at == edge.from_node


def test_extraction_is_capability_scoped_at_the_node_it_happened_on() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Overview - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Details"),
        description="open details",
        pre="Overview - Acme",
        post="Details - Acme",
    )
    recorder.record_extraction("balance", r"Balance: \$([0-9.]+)")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Home"),
        description="back home",
        pre="Details - Acme",
        post="Overview - Acme",
    )
    rec = tests.support.recording.build_recording(
        recorder, {}, {"balance": "42.00"}
    )
    assert [s.output for s in rec.extract] == ["balance"]
    details_node = rec.edges[0].to_node
    assert rec.extract_at_node == details_node
    assert rec.goal_node == rec.edges[1].to_node


def test_extraction_defaults_to_goal_when_none_recorded() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Overview - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Details"),
        description="open details",
        pre="Overview - Acme",
        post="Details - Acme",
    )
    rec = tests.support.recording.build_recording(recorder, {}, {})
    assert rec.extract == []
    assert rec.extract_at_node == rec.goal_node


def test_sensitive_literal_is_promoted_to_an_input_never_persisted() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Profile - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(
            kind="fill", value=targets.Value(literal="+1 415 555 0100")
        ),
        control=tests.support.recording.control("Phone", "text_field"),
        description="enter phone +1 415 555 0100",
        pre="Profile - Acme",
        post="Profile - Acme",
    )
    rec = tests.support.recording.build_recording(recorder, {}, {})
    edge = rec.edges[0]
    assert edge.action.value == targets.Value(param="phone")
    assert "415 555" not in edge.model_dump_json()
    assert "{{phone}}" in edge.description
    assert rec.inputs["phone"].sensitive
    assert rec.inputs["phone"].data_class == "pii"
    assert rec.promoted == [("edge-1", "phone", "pii")]


def test_plain_literal_stays_literal() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Chat - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="fill", value=targets.Value(literal="hello")),
        control=tests.support.recording.control("Message", "text_area"),
        description="say hello",
        pre="Chat - Acme",
        post="Chat - Acme",
    )
    rec = tests.support.recording.build_recording(recorder, {}, {})
    assert rec.edges[0].action.value == targets.Value(literal="hello")
    assert rec.promoted == [] and rec.inputs == {}


def test_declared_inputs_and_outputs_carry_their_class() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Overview - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Details"),
        description="open details",
        pre="Overview - Acme",
        post="Details - Acme",
    )
    rec = tests.support.recording.build_recording(
        recorder,
        {"ssn": "123-45-6789", "accountId": "13344", "note": "x1"},
        {"balance": "42.00"},
    )
    assert rec.inputs["ssn"].data_class == "pii" and rec.inputs["ssn"].sensitive
    assert rec.inputs["accountId"].data_class == "financial"
    assert rec.inputs["note"].data_class == "none"
    assert not rec.inputs["note"].sensitive
    assert rec.outputs["balance"].data_class == "financial"


def test_model_declared_class_is_unioned_with_the_detector() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Overview - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Details"),
        description="open details",
        pre="Overview - Acme",
        post="Details - Acme",
    )
    rec = tests.support.recording.build_recording(
        recorder, {"note": "x1"}, {}, input_classes={"note": "credential"}
    )
    assert rec.inputs["note"].data_class == "credential"
    assert rec.inputs["note"].sensitive
