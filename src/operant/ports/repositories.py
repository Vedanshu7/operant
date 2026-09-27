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
from typing import TYPE_CHECKING, Optional, Protocol, Tuple, runtime_checkable

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

        :return: the stored artifact with ``version`` assigned.
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

        :return: the stored graph with ``graph_version`` and timestamps
            set.
        """
        ...


# #############################################################################
# ProfileRepository
# #############################################################################


@runtime_checkable
class ProfileRepository(Protocol):
    """
    Store application profiles and the deny-by-default discovery profile.
    """

    def exists(self, profile_id: str) -> bool:
        """
        Report whether a profile is stored under ``profile_id``.
        """
        ...

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
        Write ``document`` and return the path it was written to.
        """
        ...

    def discovery_base(self) -> profile.AppProfile:
        """
        Load the deny-by-default profile a bootstrap discovery runs under.
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

    def open_approval(
        self, run_id: str, request: approval.ApprovalRequest
    ) -> str:
        """
        Record a pending approval and return its id.
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
        Record a pending intervention and return its id.
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
        Record a pending clarifying question and return its id.
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

        :return: the updated track record.
        """
        ...

    def close_samples(self, capability_id: str) -> None:
        """
        Stop counting a capability's replays so far.

        Used when it moves to another graph: they ran on something else.
        """
        ...

    def stability(
        self, capability_id: str, window: int = ...
    ) -> artifact.Stability:
        """
        Return the capability's recent track record (zeroes when none).

        :param capability_id: the capability to report on.
        :param window: how many of the most recent replays to count.
        """
        ...

    def audit(self, entry: runs.AuditEntry) -> None:
        """
        Append one line to the governance audit trail.
        """
        ...


# #############################################################################
# EdgeRecordRepository
# #############################################################################


@runtime_checkable
class EdgeRecordRepository(Protocol):
    """
    What is known about a graph version's edges: people's reviews of its
    unknown steps, and how often each edge worked.
    """

    def is_approved(
        self, vendor_id: str, graph_version: int, key: Tuple[str, str, str]
    ) -> bool:
        """
        Report whether a person reviewed this step on this graph version.
        """
        ...

    def approve(
        self,
        vendor_id: str,
        graph_version: int,
        keys: collections.abc.Sequence[Tuple[str, str, str]],
        *,
        by: str,
    ) -> None:
        """
        Record that a person reviewed these steps.
        """
        ...

    def record_outcome(
        self, vendor_id: str, graph_version: int, edge_id: str, *, passed: bool
    ) -> None:
        """
        Count one run of an edge.
        """
        ...

    def failing(self, vendor_id: str) -> collections.abc.Set[str]:
        """
        Return edges that failed at least twice on a version and never passed.
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
