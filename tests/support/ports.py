"""
Minimal in-memory fakes that satisfy the port protocols.
"""

from __future__ import annotations

import collections.abc
import pathlib
from typing import Any, Dict, List, Optional, Tuple

import operant.domain.events as events
import operant.domain.models.actions as actions
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.llm as llm
import operant.domain.models.results as results
import operant.domain.models.runs as runs
import operant.domain.models.tools as mttools


def blank_digest() -> digest.ScreenDigest:
    """
    Build an empty digest.
    """
    return digest.ScreenDigest(app="", window_title="", text="")


# #############################################################################
# FakeSurface
# #############################################################################


class FakeSurface:
    """
    Record actions; observes a fixed digest.
    """

    def __init__(self) -> None:
        self.performed: List[actions.SurfaceAction] = []

    def snapshot(self) -> digest.ScreenDigest:
        return blank_digest()

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> object:
        self.performed.append(action)
        return None

    def screenshot(self, path: pathlib.Path) -> bool:
        return False

    def retarget(
        self, app_name: str, window_title_pattern: str
    ) -> Tuple[str, str]:
        return ("", "")

    def target_text_for(self, ref: Optional[str]) -> str:
        return ""

    def start_human_capture(
        self, on_action: collections.abc.Callable[[str], None]
    ) -> None:
        pass

    def stop_human_capture(self) -> None:
        pass

    def start_capture(
        self,
        out_dir: pathlib.Path,
        task: str,
        window: Optional[collections.abc.Mapping[str, Optional[str]]],
        video: bool = True,
    ) -> bool:
        return False

    def stop_capture(self) -> collections.abc.Mapping[str, Any]:
        return {}

    def grant_scope(self, grant: Any) -> None:
        pass

    def inject_session_expiry(self) -> None:
        pass

    def close(self) -> None:
        pass


# #############################################################################
# FakeTool
# #############################################################################


class FakeTool:
    """
    Serve every action kind and reports ok.
    """

    spec = mttools.ToolSpec(name="fake", version="0", serves=frozenset())

    def health(self) -> mttools.ToolHealth:
        return mttools.ToolHealth(status="ok")

    def execute(
        self, action: actions.SurfaceAction, ctx: mttools.ExecutionContext
    ) -> mttools.ToolResult:
        return mttools.ToolResult(status="ok", verified=True)


# #############################################################################
# FakeArtifactRepository
# #############################################################################


class FakeArtifactRepository:
    """
    Artifacts in a dict keyed by id, one version each.
    """

    def __init__(self) -> None:
        self.items: Dict[str, artifact.CapabilityArtifact] = {}

    def get(
        self, artifact_id: str, version: Optional[int] = None
    ) -> artifact.CapabilityArtifact:
        return self.items[artifact_id]

    def head(self, artifact_id: str) -> Optional[int]:
        return 1 if artifact_id in self.items else None

    def versions(self, artifact_id: str) -> collections.abc.Sequence[int]:
        return [1] if artifact_id in self.items else []

    def list(self) -> collections.abc.Sequence[artifact.CapabilityArtifact]:
        return list(self.items.values())

    def save_new_version(
        self, document: artifact.CapabilityArtifact
    ) -> artifact.CapabilityArtifact:
        self.items[document.id] = document
        return document

    def exists(self, artifact_id: str) -> bool:
        return artifact_id in self.items


# #############################################################################
# FakeGraphRepository
# #############################################################################


class FakeGraphRepository:
    """
    Graphs in a dict keyed by vendor, one version each.
    """

    def __init__(self) -> None:
        self.items: Dict[str, graph.AppGraph] = {}

    def versions(self, vendor: str) -> collections.abc.Sequence[int]:
        return [1] if vendor in self.items else []

    def head(self, vendor: str) -> Optional[int]:
        return 1 if vendor in self.items else None

    def get(self, vendor: str, version: Optional[int] = None) -> graph.AppGraph:
        return self.items[vendor]

    def exists(self, vendor: str) -> bool:
        return vendor in self.items

    def save_new_version(self, document: graph.AppGraph) -> graph.AppGraph:
        self.items[document.vendor_id] = document
        return document


# #############################################################################
# FakeProfileRepository
# #############################################################################


class FakeProfileRepository:
    """
    Profiles in a dict keyed by id.
    """

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.items: Dict[str, Any] = {}

    def get(self, profile_id: str) -> Any:
        return self.items[profile_id]

    def list(self) -> collections.abc.Sequence[Any]:
        return list(self.items.values())

    def save(self, document: Any) -> pathlib.Path:
        self.items[document.vendor_id] = document
        return self.root / f"{document.vendor_id}.json"

    def discovery_base(self) -> pathlib.Path:
        return self.root / "discovery"


# #############################################################################
# FakeRunRepository
# #############################################################################


class FakeRunRepository:
    """
    Run and HITL rows in dicts.
    """

    def __init__(self) -> None:
        self.runs: Dict[str, runs.RunRecord] = {}
        self.events: List[runs.RunEventIndex] = []
        self.audit_trail: List[runs.AuditEntry] = []
        self.track: Dict[str, artifact.Stability] = {}

    def create(self, run: runs.RunRecord) -> None:
        self.runs[run.id] = run

    def update_status(
        self,
        run_id: str,
        status: runs.RunStatus,
        *,
        result: Optional[results.ReplayResult] = None,
        error: Optional[str] = None,
    ) -> None:
        import dataclasses

        self.runs[run_id] = dataclasses.replace(
            self.runs[run_id], status=status, result=result, error=error
        )

    def get(self, run_id: str) -> runs.RunRecord:
        return self.runs[run_id]

    def list(
        self, criteria: runs.RunFilter
    ) -> collections.abc.Sequence[runs.RunRecord]:
        return list(self.runs.values())

    def index_event(self, run_id: str, event: events.BaseEvent) -> None:
        self.events.append(
            runs.RunEventIndex(
                run_id=run_id,
                seq=event.seq or 0,
                type=event.type,
                at=event.at or "",
                summary=event.summary,
            )
        )

    def open_approval(self, run_id: str, request: Any) -> str:
        return "approval-1"

    def decide_approval(self, approval_id: str, decision: Any) -> None:
        pass

    def open_intervention(
        self, run_id: str, request: runs.InterventionRequest
    ) -> str:
        return "intervention-1"

    def update_intervention(
        self,
        intervention_id: str,
        state: runs.InterventionState,
        *,
        note: Optional[str] = None,
        human_actions: Optional[collections.abc.Sequence[str]] = None,
    ) -> None:
        pass

    def open_clarification(self, run_id: str, question: str) -> str:
        return "clarification-1"

    def answer_clarification(self, clarification_id: str, answer: str) -> None:
        pass

    def record_stability(
        self, capability_id: str, run_id: str, *, succeeded: bool
    ) -> artifact.Stability:
        current = self.stability(capability_id)
        updated = artifact.Stability(
            runs=current.runs + 1,
            successes=current.successes + (1 if succeeded else 0),
        )
        self.track[capability_id] = updated
        return updated

    def stability(self, capability_id: str) -> artifact.Stability:
        return self.track.get(capability_id, artifact.Stability())

    def audit(self, entry: runs.AuditEntry) -> None:
        self.audit_trail.append(entry)


# #############################################################################
# FakeSecretRefRepository
# #############################################################################


class FakeSecretRefRepository:
    """
    Secret references in a dict keyed by name.
    """

    def __init__(self) -> None:
        self.items: Dict[str, runs.SecretRefMeta] = {}

    def list(self) -> collections.abc.Sequence[runs.SecretRefMeta]:
        return list(self.items.values())

    def upsert(self, meta: runs.SecretRefMeta) -> None:
        self.items[meta.name] = meta

    def delete(self, name: str) -> None:
        del self.items[name]


# #############################################################################
# FakeEvidenceSink
# #############################################################################


class FakeEvidenceSink:
    """
    Collect emitted events in memory.
    """

    def __init__(self, root: pathlib.Path) -> None:
        self.run_id = "run-1"
        self.dir = root
        self.redactor: Any = None
        self.emitted: List[events.BaseEvent] = []

    def emit(self, event: events.BaseEvent) -> None:
        self.emitted.append(event)

    def event(self, type_: str, **data: Any) -> None:
        model = events.EVENT_REGISTRY[type_]
        self.emit(model.model_validate({"type": type_, **data}))

    def screenshot(self, target: Any, label: str) -> str:
        return ""


# #############################################################################
# FakeApprover
# #############################################################################


class FakeApprover:
    """
    Answers every request with a fixed decision.
    """

    def __init__(self, decision: Any) -> None:
        self.decision = decision
        self.asked: List[Any] = []

    def ask(self, request: Any) -> Any:
        self.asked.append(request)
        return self.decision


# #############################################################################
# FakeClarifier
# #############################################################################


class FakeClarifier:
    """
    Answers every question with a fixed string.
    """

    def __init__(self, answer: str = "") -> None:
        self.answer = answer

    def ask(self, question: str, *, run_id: str) -> str:
        return self.answer


# #############################################################################
# FakeLlmClient
# #############################################################################


class FakeLlmClient:
    """
    Return scripted turns in order.
    """

    def __init__(self, turns: collections.abc.Sequence[llm.LlmTurn]) -> None:
        self.turns = list(turns)
        self.seen: List[collections.abc.Sequence[llm.ChatMessage]] = []

    def complete(
        self,
        messages: collections.abc.Sequence[llm.ChatMessage],
        *,
        tools: collections.abc.Sequence[llm.ToolSchema],
    ) -> llm.LlmTurn:
        self.seen.append(messages)
        return self.turns.pop(0) if self.turns else llm.LlmTurn()


# #############################################################################
# FakePreferenceStore
# #############################################################################


class FakePreferenceStore:
    """
    An in-memory ``PreferenceStore`` for learner tests.
    """

    def __init__(self, initial: Optional[Dict[str, str]] = None) -> None:
        self.saved: List[Dict[str, str]] = []
        self._prefs = dict(initial or {})

    def load(self) -> Dict[str, str]:
        return dict(self._prefs)

    def save(self, preferences: Dict[str, str]) -> None:
        self._prefs = dict(preferences)
        self.saved.append(dict(preferences))
