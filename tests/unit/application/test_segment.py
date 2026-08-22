"""
Cross-app recordings: segmentation at app-switch boundaries, per-vendor graph
commits, and the caller's invoke edge (the shape traversal replays).
"""

import pathlib

import operant.application.capabilities
import operant.application.recorder.recording
import operant.application.recorder.segment
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as rggraphs
import tests.support.recording


def _cross_app_recorder() -> operant.application.recorder.recording.Recorder:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.set_binding("parabank", "Google Chrome", "ParaBank")
    recorder.start("Overview - ParaBank")
    recorder.record_extraction("balance", r"Balance: \$([0-9.]+)")
    recorder.set_binding("whatsapp", "WhatsApp", ".*")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="launch", app="WhatsApp"),
        control=None,
        description="open WhatsApp",
        pre="Overview - ParaBank",
        post="WhatsApp",
    )
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="fill", value=targets.Value(literal="hi")),
        control=tests.support.recording.control("Message", "text_field"),
        description="type the message",
        pre="WhatsApp",
        post="WhatsApp",
    )
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Send", "button"),
        description="send it",
        pre="WhatsApp",
        post="WhatsApp",
    )
    return recorder


def _build(recorder: operant.application.recorder.recording.Recorder):
    return tests.support.recording.build_recording(
        recorder,
        {},
        {"balance": "42"},
        capability_id="pb-to-wa",
        goal="send the balance on whatsapp",
        run_id="run",
    )


def test_segmentation_rewrites_crossing_edge_to_invoke() -> None:
    caller, segments = operant.application.recorder.segment.segment_recording(
        _build(_cross_app_recorder())
    )
    assert [s.vendor_id for s in segments] == ["whatsapp"]
    segment = segments[0]
    assert [e.description for e in segment.edges] == [
        "type the message",
        "send it",
    ]
    assert segment.entry_node == segment.goal_node
    assert caller.vendor_id == "parabank"
    assert len(caller.edges) == 1
    invoke = caller.edges[0]
    assert invoke.action.kind == "invoke"
    assert invoke.action.graph_ref is not None
    assert invoke.action.graph_ref.graph_id == "whatsapp"
    assert invoke.from_node == invoke.to_node
    assert caller.goal_node == invoke.to_node
    assert caller.extract_at_node in {n.id for n in caller.nodes}
    assert caller.policy_scope.required_action_kinds == ["invoke"]


def test_single_app_recording_passes_through() -> None:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.set_binding("parabank", "Google Chrome", "ParaBank")
    recorder.start("Overview - ParaBank")
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Details"),
        description="open details",
        pre="Overview - ParaBank",
        post="Details - ParaBank",
    )
    caller, segments = operant.application.recorder.segment.segment_recording(
        _build(recorder)
    )
    assert segments == []
    assert len(caller.edges) == 1 and caller.edges[0].action.kind == "click"


def test_commit_writes_both_graphs_and_remaps_the_invoke_target(
    tmp_path: pathlib.Path,
) -> None:
    graphs = rggraphs.FileGraphRepository(tmp_path / "graphs")
    artifacts = artifact.FileArtifactRepository(tmp_path / "artifacts")
    cap, caller_graph = operant.application.capabilities.commit_recording(
        _build(_cross_app_recorder()),
        graph_store=graphs,
        artifact_store=artifacts,
    )

    assert caller_graph.vendor_id == "parabank"
    assert graphs.exists("whatsapp")
    whatsapp = graphs.get("whatsapp")
    assert whatsapp.app_name == "WhatsApp"
    assert len(whatsapp.edges) == 2

    invoke = next(e for e in caller_graph.edges if e.action.kind == "invoke")
    assert invoke.action.graph_ref is not None
    assert invoke.action.graph_ref.graph_id == "whatsapp"
    assert invoke.action.graph_ref.target_node in {n.id for n in whatsapp.nodes}
    assert invoke.id in cap.compiled_path
    assert cap.vendor_id == "parabank"
