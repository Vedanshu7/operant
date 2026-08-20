"""
Persistence ports for artifacts, graphs, profiles, runs, and secrets.

All methods are synchronous; an async database adapter bridges.
Versioned documents (artifacts, graphs) are immutable per version and
grow by ``save_new_version``.

Import as:

import operant.ports.repositories as repos
"""

from __future__ import annotations

import collections.abc
import pathlib
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

import operant.domain.events as events
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.domain.models.results as results
import operant.domain.models.runs as runs

if TYPE_CHECKING:
    import operant.domain.approval as approval
    import operant.domain.profile as profile


# #############################################################################
# ArtifactRepository
# #############################################################################


@runtime_checkable
class ArtifactRepository(Protocol):
    """
    Capability artifacts, versioned per id.
    """

    def get(
        self, artifact_id: str, version: Optional[int] = None
    ) -> artifact.CapabilityArtifact:
        """
        Load one version (default: head).
        """
        ...

    def head(self, artifact_id: str) -> Optional[int]:
        """
        Return the latest version number, or ``None`` when absent.
        """
        ...

    def versions(self, artifact_id: str) -> collections.abc.Sequence[int]:
        """
        Return every stored version number, ascending.
        """
        ...

    def list(self) -> collections.abc.Sequence[artifact.CapabilityArtifact]:
        """
        Return the head version of every artifact, by id.
        """
        ...

    def save_new_version(
        self, document: artifact.CapabilityArtifact
    ) -> artifact.CapabilityArtifact:
        """
        Store ``document`` as the next version of its id.

        :return: The stored artifact with ``version`` assigned.
        """
        ...

    def exists(self, artifact_id: str) -> bool:
        """
        Report whether any version of ``artifact_id`` is stored.
        """
        ...


# #############################################################################
# GraphRepository
# #############################################################################


@runtime_checkable
class GraphRepository(Protocol):
    """
    Application graphs, versioned per vendor.
    """

    def versions(self, vendor: str) -> collections.abc.Sequence[int]:
        """
        Return every stored version number, ascending.
        """
        ...

    def head(self, vendor: str) -> Optional[int]:
        """
        Return the latest version number, or ``None`` when absent.
        """
        ...

    def get(self, vendor: str, version: Optional[int] = None) -> graph.AppGraph:
        """
        Load one version (default: head).
        """
        ...

    def exists(self, vendor: str) -> bool:
        """
        Report whether any version for ``vendor`` is stored.
        """
        ...

    def save_new_version(self, document: graph.AppGraph) -> graph.AppGraph:
        """
        Store ``document`` as the next version of its vendor.

        :return: The stored graph with ``graph_version`` and timestamps
            set.
        """
        ...


# #############################################################################
# ProfileRepository
# #############################################################################


@runtime_checkable
class ProfileRepository(Protocol):
    """
    Application profiles and where discovery evidence is rooted.
    """

    def get(self, profile_id: str) -> profile.AppProfile:
        """
        Load one profile.
        """
        ...

    def list(self) -> collections.abc.Sequence[profile.AppProfile]:
        """
        Return every profile, by id.
        """
        ...

    def save(self, document: profile.AppProfile) -> pathlib.Path:
        """
        Write ``document`` and returns the path it was written to.
        """
        ...

    def discovery_base(self) -> pathlib.Path:
        """
        Return the directory discovery runs write evidence under.
        """
        ...


# #############################################################################
# RunRepository
# #############################################################################


@runtime_checkable
class RunRepository(Protocol):
    """
    Runs, their event index, and the human-in-the-loop rows.
    """

    def create(self, run: runs.RunRecord) -> None:
        """
        Insert a new run.
        """
        ...

    def update_status(
        self,
        run_id: str,
        status: runs.RunStatus,
        *,
        result: Optional[results.ReplayResult] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Move a run to ``status``, recording its result or error.
        """
        ...

    def get(self, run_id: str) -> runs.RunRecord:
        """
        Load one run.
        """
        ...

    def list(
        self, criteria: runs.RunFilter
    ) -> collections.abc.Sequence[runs.RunRecord]:
        """
        Return runs matching ``criteria``, newest first.
        """
        ...

    def index_event(self, run_id: str, event: events.BaseEvent) -> None:
        """
        Add an evidence event to the run's queryable index.
        """
        ...

    def open_approval(
        self, run_id: str, request: approval.ApprovalRequest
    ) -> str:
        """
        Record a pending approval and returns its id.
        """
        ...

    def decide_approval(
        self, approval_id: str, decision: approval.ApprovalDecision
    ) -> None:
        """
        Record the human's decision on a pending approval.
        """
        ...

    def open_intervention(
        self, run_id: str, request: runs.InterventionRequest
    ) -> str:
        """
        Record a pending intervention and returns its id.
        """
        ...

    def update_intervention(
        self,
        intervention_id: str,
        state: runs.InterventionState,
        *,
        note: Optional[str] = None,
        human_actions: Optional[collections.abc.Sequence[str]] = None,
    ) -> None:
        """
        Move an intervention to ``state`` with the human's notes.
        """
        ...

    def open_clarification(self, run_id: str, question: str) -> str:
        """
        Record a pending clarifying question and returns its id.
        """
        ...

    def answer_clarification(self, clarification_id: str, answer: str) -> None:
        """
        Record the answer to a clarifying question.
        """
        ...

    def record_stability(
        self, capability_id: str, run_id: str, *, succeeded: bool
    ) -> artifact.Stability:
        """
        Add one replay to a capability's track record.

        :return: The updated track record.
        """
        ...

    def stability(self, capability_id: str) -> artifact.Stability:
        """
        Return the capability's track record (zeroes when none).
        """
        ...

    def audit(self, entry: runs.AuditEntry) -> None:
        """
        Append one line to the governance audit trail.
        """
        ...


# #############################################################################
# SecretRefRepository
# #############################################################################


@runtime_checkable
class SecretRefRepository(Protocol):
    """
    Declared secret references: locators, never values.
    """

    def list(self) -> collections.abc.Sequence[runs.SecretRefMeta]:
        """
        Return every declared reference, by name.
        """
        ...

    def upsert(self, meta: runs.SecretRefMeta) -> None:
        """
        Create or replaces the reference named ``meta.name``.
        """
        ...

    def delete(self, name: str) -> None:
        """
        Remove a reference.
        """
        ...
