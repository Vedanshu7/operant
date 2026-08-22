"""
Run discovery and replay on worker threads and streams their events.

The library engine is synchronous and blocks on human decisions, so each
run executes in its own thread. This manager owns the single sequence of
stream events per run (so the SSE cursor and the DB index agree),
bridges blocked worker threads to HTTP routes through ``PendingAnswer``,
and mirrors the control broker's interventions into the database and the
event stream.

Import as:

import operant.server.jobs.manager as jmmanage
"""

from __future__ import annotations

import asyncio
import collections.abc
import dataclasses
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

import operant.adapters.llm.litellm_client as litecli
import operant.application.approval as approval
import operant.application.context as accontex
import operant.application.discovery.config as config
import operant.application.escalation as escal
import operant.application.usecases.discover as discover
import operant.application.usecases.replay as replay
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.runs as mrruns
import operant.domain.secrets as odsec
import operant.helpers.ids as ids
import operant.helpers.logging as logging
import operant.helpers.time as time
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.infra.repositories.runs as rrruns
import operant.infra.settings as issettin
import operant.ports.secrets as secrets
import operant.server.jobs.hitl as hitl
import operant.server.jobs.hub as jhhub
import operant.server.jobs.lease as jllease
import operant.server.jobs.pending as jppendin

_LOG = logging.get_logger(__name__)

_SKIP_STREAM = frozenset(
    {
        "approval_requested",
        "approval_resolved",
        "clarify",
        "clarification_answered",
        "control_transition",
        "escalation_raised",
        "escalation_resolved",
    }
)

_RESULT_STATUS: Dict[str, mrruns.RunStatus] = {
    "success": "succeeded",
    "business_outcome": "business_outcome",
    "escalated": "escalated",
    "failure": "failed",
}


# #############################################################################
# _Handle
# #############################################################################


@dataclasses.dataclass
class _Handle:
    """
    Mutable per-run bookkeeping the worker and routes share.
    """

    run_id: str
    kind: mrruns.RunKind
    goal: str
    capability: str
    cancelled: threading.Event = dataclasses.field(
        default_factory=threading.Event
    )
    status: mrruns.RunStatus = "queued"
    broker: Optional[escal.ControlBroker] = None
    iv_db_id: Optional[str] = None
    iv_broker_id: Optional[str] = None
    last_state: str = "agent"


# #############################################################################
# RunManager
# #############################################################################


class RunManager:
    """
    Start runs, streams their events, and routes human answers.
    """

    def __init__(
        self,
        *,
        settings: issettin.OperantSettings,
        factory: accontex.ContextBuilder,
        artifacts: artifact.FileArtifactRepository,
        graphs: rggraphs.FileGraphRepository,
        profiles: rpprofil.FileProfileRepository,
        secret_store: secrets.SecretStore,
        runs: rrruns.SqlRunRepository,
        hub: jhhub.EventHub,
        lease: jllease.DriverLease,
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._artifacts = artifacts
        self._graphs = graphs
        self._profiles = profiles
        self._secret_store = secret_store
        self._runs = runs
        self._hub = hub
        self._lease = lease
        self._lock = threading.Lock()
        self._handles: Dict[str, _Handle] = {}
        self._pending: Dict[str, jppendin.PendingAnswer[object]] = {}
        self._seq: Dict[str, int] = {}

    def start_replay(
        self, request: replay.ReplayRequest, *, created_by: str = ""
    ) -> mrruns.RunRecord:
        """
        Queue a replay run and returns its initial record.
        """
        capability = self._artifacts.get(request.capability_id)
        run_id = ids.run_id("replay")
        record = mrruns.RunRecord(
            id=run_id,
            kind="replay",
            status="queued",
            vendor_id=capability.vendor_id,
            capability_id=request.capability_id,
            tenant=request.tenant or capability.default_tenant,
            goal=capability.name or request.capability_id,
            evidence_dir=run_id,
            created_at=time.iso_now(),
            inputs=dict(request.inputs or {}),
        )
        self._launch(record, lambda h: self._run_replay(h, request))
        stored = self._runs.get(run_id)
        return stored

    def start_discovery(
        self, request: discover.DiscoverRequest, *, created_by: str = ""
    ) -> mrruns.RunRecord:
        """
        Queue a discovery run and returns its initial record.
        """
        run_id = ids.run_id("discovery")
        record = mrruns.RunRecord(
            id=run_id,
            kind="discovery",
            status="queued",
            vendor_id="",
            capability_id=request.capability_id,
            tenant=request.tenant,
            goal=request.goal,
            evidence_dir=run_id,
            created_at=time.iso_now(),
            inputs=dict(request.inputs or {}),
        )
        self._launch(record, lambda h: self._run_discovery(h, request))
        stored = self._runs.get(run_id)
        return stored

    def replay_stream(
        self, run_id: str, after_seq: int
    ) -> List[jhhub.SseEnvelope]:
        """
        Return the run's stream events after ``after_seq`` for replay.
        """
        run = self._runs.get(run_id)
        events = [
            jhhub.SseEnvelope(
                run_id=event.run_id,
                type=event.type,
                at=event.at,
                seq=event.seq,
                summary=event.summary,
                data=event.data,
                run_status=run.status,
                screenshot=event.screenshot,
            )
            for event in self._runs.stream_events(run_id, after_seq)
        ]
        return events

    def is_terminal(self, run_id: str) -> bool:
        """
        Whether the run has reached a terminal status.
        """
        terminal = self._runs.get(run_id).status in mrruns.TERMINAL_STATUSES
        return terminal

    def answer_approval(
        self, approval_id: str, *, approved: bool, remember: str, note: str
    ) -> None:
        """
        Deliver a human's approval decision to the waiting worker.
        """
        decision = daapprov.ApprovalDecision(
            approved=approved,
            remember="process" if remember == "process" else "once",
            by="console",
            note=note,
        )
        self._deliver(approval_id, decision)

    def answer_clarification(self, clarification_id: str, answer: str) -> None:
        """
        Deliver a clarifying answer to the waiting worker.
        """
        self._deliver(clarification_id, answer)

    def answer_credential(
        self,
        request_id: str,
        *,
        value: Optional[str] = None,
        locator: Optional[str] = None,
    ) -> None:
        """
        Deliver an operator-provided credential to the waiting worker.

        The grant is passed in memory only; it is never persisted.
        """
        grant = odsec.CredentialGrant(
            value=value or None, locator=locator or None
        )
        self._deliver(request_id, grant)

    def take_intervention(self, intervention_id: str) -> None:
        """
        Transfer the live session to the operator.
        """
        handle, broker = self._broker_for(intervention_id)
        broker.take_control(handle.iv_broker_id or "")

    def hand_back(self, intervention_id: str, note: str) -> None:
        """
        Return the live session to the automation.
        """
        handle, broker = self._broker_for(intervention_id)
        broker.hand_back(handle.iv_broker_id or "", note)

    def abandon(self, intervention_id: str, note: str) -> None:
        """
        End the run: the operator could not recover it.
        """
        handle, broker = self._broker_for(intervention_id)
        broker.abandon(handle.iv_broker_id or "", note)

    def cancel(self, run_id: str) -> None:
        """
        Request cancellation: denies any wait and abandons a hand-off.

        A run with no live worker (e.g. one orphaned by a server
        restart) cannot be signalled, so its row is settled to
        ``cancelled`` directly rather than lingering in a waiting state
        forever.
        """
        handle = self._handles.get(run_id)
        if handle is None:
            # No live worker (e.g. orphaned by a restart): settle directly.
            self._settle_orphan(run_id, "cancelled", "run cancelled")
        else:
            # Live worker: signal it and deny any pending wait.
            handle.cancelled.set()
            if handle.broker is not None and handle.iv_broker_id is not None:
                handle.broker.abandon(handle.iv_broker_id, "run cancelled")
            for answer_id, pending in list(self._pending.items()):
                if answer_id.split("~", 1)[0] == run_id:
                    pending.set(
                        daapprov.ApprovalDecision(
                            approved=False,
                            by="console",
                            note="run cancelled",
                        )
                    )

    def reconcile_interrupted(self) -> int:
        """
        Settle runs left non-terminal by a previous process.

        Called at startup: any run still marked queued/running/waiting has no
        worker in this process, so it is failed rather than left as a zombie
        the UI can neither advance nor cancel.
        """
        count = 0
        for run in self._runs.list(mrruns.RunFilter(limit=1000)):
            if run.status not in mrruns.TERMINAL_STATUSES:
                self._runs.update_status(
                    run.id,
                    "failed",
                    error="run interrupted by a server restart",
                )
                self._settle_pending_hitl(run.id, "run interrupted")
                count += 1
        return count

    def _settle_orphan(
        self, run_id: str, status: mrruns.RunStatus, note: str
    ) -> None:
        """
        Settle a workerless run's row and emit its terminal status.
        """
        run = self._runs.get(run_id)
        if run.status not in mrruns.TERMINAL_STATUSES:
            self._runs.update_status(run_id, status, error=note)
            self._settle_pending_hitl(run_id, note)
            self._emit(
                jhhub.SseEnvelope(
                    run_id=run_id,
                    type="run_status",
                    summary=note,
                    run_status=status,
                )
            )

    def _settle_pending_hitl(self, run_id: str, note: str) -> None:
        """
        Resolve a dead run's open approvals, interventions, and questions so
        they do not linger in the operator inbox nor 404 when answered.
        """
        for approval_row in self._runs.run_approvals(run_id):
            if approval_row.status == "pending":
                self._runs.decide_approval(
                    approval_row.id,
                    daapprov.ApprovalDecision(
                        approved=False, by="timeout", note=note
                    ),
                )
        for iv in self._runs.run_interventions(run_id):
            if iv.state in ("paused", "human"):
                self._runs.update_intervention(iv.id, "timed_out", note=note)
        for clar in self._runs.run_clarifications(run_id):
            if clar.status == "pending":
                self._runs.answer_clarification(clar.id, "")

    def _launch(
        self,
        record: mrruns.RunRecord,
        target: collections.abc.Callable[[_Handle], None],
    ) -> None:
        """
        Persist the run and start its worker thread.
        """
        self._runs.create(record)
        handle = _Handle(
            run_id=record.id,
            kind=record.kind,
            goal=record.goal,
            capability=record.capability_id or record.goal,
        )
        with self._lock:
            self._handles[record.id] = handle
            self._seq[record.id] = 0
        thread = threading.Thread(
            target=self._guard, args=(handle, target), daemon=True
        )
        thread.start()

    def _guard(
        self, handle: _Handle, target: collections.abc.Callable[[_Handle], None]
    ) -> None:
        """
        Acquire the driver lease, run the target, and settle on failure.
        """
        self._set_status(handle, "waiting_driver")
        self._lease.acquire(handle.run_id)
        try:
            self._set_status(handle, "running")
            target(handle)
        except Exception as err:
            _LOG.exception("run %s failed", handle.run_id)
            self._runs.update_status(handle.run_id, "failed", error=str(err))
            self._emit(
                jhhub.SseEnvelope(
                    run_id=handle.run_id,
                    type="run_status",
                    summary=f"run failed: {err}",
                    run_status="failed",
                )
            )
        finally:
            self._lease.release(handle.run_id)

    def _run_replay(self, handle: _Handle, request: replay.ReplayRequest) -> None:
        """
        Execute a replay run, record stability, and emit the outcome.
        """
        approver = self._approver(handle)
        result = replay.execute_replay(
            request,
            factory=self._factory,
            artifacts=self._artifacts,
            graphs=self._graphs,
            profiles=self._profiles,
            approver=approver,
            run_identifier=handle.run_id,
            on_context=lambda ctx: self._wire(handle, ctx),
        )
        if request.capability_id:
            self._runs.record_stability(
                request.capability_id,
                handle.run_id,
                succeeded=replay.is_success(result),
            )
        status = _RESULT_STATUS.get(result.status, "failed")
        self._runs.update_status(handle.run_id, status, result=result)
        self._emit_terminal(handle, status, f"replay {result.status}")

    def _run_discovery(
        self, handle: _Handle, request: discover.DiscoverRequest
    ) -> None:
        """
        Execute a discovery run with the UI-backed HITL adapters.
        """
        approver = self._approver(handle)
        clarifier = hitl.UiClarifier(
            handle.run_id,
            self._runs,
            self._emit,
            self._register,
            lambda status: self._set_status(handle, status),
            timeout_s=self._settings.approval.clarification_timeout_s,
        )
        credentials = hitl.UiCredentialRequester(
            handle.run_id,
            self._emit,
            self._register,
            lambda status: self._set_status(handle, status),
            timeout_s=self._settings.approval.clarification_timeout_s,
        )
        llm = litecli.LiteLlmClient(self._settings.discovery)
        outcome = discover.execute_discovery(
            request,
            factory=self._factory,
            artifacts=self._artifacts,
            graphs=self._graphs,
            profiles=self._profiles,
            llm=llm,
            secret_store=self._secret_store,
            model_name=self._settings.discovery.model or "",
            clarifier=clarifier,
            approver=approver,
            credential_requester=credentials,
            run_identifier=handle.run_id,
            on_context=lambda ctx: self._wire(handle, ctx),
        )
        self._finish_discovery(handle, outcome)

    def _finish_discovery(
        self,
        handle: _Handle,
        outcome: Union[discover.DiscoverOutcome, config.DiscoveryFailure],
    ) -> None:
        """
        Settle the run's row and stream from the discovery outcome.
        """
        if isinstance(outcome, config.DiscoveryFailure):
            # Discovery failed: settle the row with the reason.
            self._runs.update_status(
                handle.run_id, "failed", error=outcome.reason
            )
            self._emit_terminal(
                handle, "failed", f"discovery failed: {outcome.reason}"
            )
        else:
            # Discovery succeeded: settle with the new capability.
            self._runs.update_status(handle.run_id, "succeeded")
            self._emit_terminal(
                handle, "succeeded", f"discovered {outcome.capability.id}"
            )

    def _wire(self, handle: _Handle, context: accontex.RunContext) -> None:
        """
        Attach the manager's log and broker listeners to a run context.
        """
        handle.broker = context.broker
        context.log.listeners.append(self._log_listener(handle))
        context.broker.listeners.append(self._broker_listener(handle))

    def _approver(self, handle: _Handle) -> approval.RememberingApprover:
        """
        Build the remembering approver wrapping the UI approver.
        """
        inner = hitl.UiApprover(
            handle.run_id,
            self._runs,
            self._emit,
            self._register,
            lambda status: self._set_status(handle, status),
            timeout_s=self._settings.approval.timeout_s,
        )
        approver = approval.RememberingApprover(inner, cache={})
        return approver

    def _log_listener(
        self, handle: _Handle
    ) -> collections.abc.Callable[[dict[str, Any]], None]:
        """
        Build a listener that streams evidence-log entries as SSE.
        """

        def listen(entry: Dict[str, Any]) -> None:
            type_ = str(entry.get("type", ""))
            if type_ in _SKIP_STREAM:
                return
            data = {
                key: value
                for key, value in entry.items()
                if key not in {"seq", "at", "type", "summary"}
            }
            self._emit(
                jhhub.SseEnvelope(
                    run_id=handle.run_id,
                    type=type_,
                    summary=str(entry.get("summary") or ""),
                    data=data,
                    run_status=handle.status,
                    screenshot=entry.get("file"),
                )
            )

        return listen

    def _broker_listener(
        self, handle: _Handle
    ) -> collections.abc.Callable[[], None]:
        """
        Build a listener mirroring broker state into runs and the stream.
        """

        def listen() -> None:
            broker = handle.broker
            if broker is None:
                return
            pending = broker.pending
            if pending is not None and handle.iv_broker_id != pending.id:
                self._open_intervention(handle, pending)
            if broker.state != handle.last_state:
                self._on_state(handle, broker.state)
                handle.last_state = broker.state

        return listen

    def _open_intervention(
        self,
        handle: _Handle,
        pending: escal.InterventionRequest,
    ) -> None:
        """
        Open an intervention row and stream the escalation event.
        """
        request = mrruns.InterventionRequest(
            kind=handle.kind,
            capability=handle.capability,
            goal=handle.goal,
            reason=pending.reason,
            page_title=pending.page_title,
            edge_id=pending.edge_id,
            screenshot_file=pending.screenshot_file,
        )
        db_id = self._runs.open_intervention(handle.run_id, request)
        handle.iv_db_id = db_id
        handle.iv_broker_id = pending.id
        self._set_status(handle, "waiting_intervention")
        self._emit_intervention(
            handle, "escalation_raised", "waiting_intervention"
        )

    def _on_state(self, handle: _Handle, state: str) -> None:
        """
        React to a broker state change on the run's open intervention.
        """
        if handle.iv_db_id is not None:
            if state == "human":
                # Operator took control: mark the intervention human-held.
                self._runs.update_intervention(handle.iv_db_id, "human")
                self._emit_intervention(
                    handle, "control_transition", "waiting_intervention"
                )
            elif state == "resuming":
                # Operator handed back: resolve the intervention as resumed.
                self._resolve_intervention(handle, "resumed")
            elif state == "agent" and handle.last_state in {"paused", "human"}:
                # Dropped back to the agent after a hand-off: resolve abandoned.
                self._resolve_intervention(handle, "abandoned")

    def _resolve_intervention(
        self, handle: _Handle, outcome: mrruns.InterventionState
    ) -> None:
        """
        Close the open intervention with an outcome and resume the run.
        """
        if handle.iv_db_id is not None and handle.broker is not None:
            self._runs.update_intervention(
                handle.iv_db_id,
                outcome,
                human_actions=handle.broker.human_actions_so_far,
            )
            self._set_status(handle, "running")
            self._emit_intervention(handle, "control_transition", "running")
            handle.iv_db_id = None
            handle.iv_broker_id = None

    def _emit_intervention(
        self, handle: _Handle, type_: str, run_status: mrruns.RunStatus
    ) -> None:
        """
        Stream the open intervention's current state as an SSE event.
        """
        if handle.iv_db_id is not None:
            record = self._runs.get_intervention(handle.iv_db_id)
            state = record.state if record else ""
            self._emit(
                jhhub.SseEnvelope(
                    run_id=handle.run_id,
                    type=type_,
                    summary=f"control: {state}",
                    data=(
                        {"intervention": dataclasses.asdict(record)}
                        if record
                        else {}
                    ),
                    run_status=run_status,
                )
            )

    def _emit_terminal(
        self, handle: _Handle, status: mrruns.RunStatus, summary: str
    ) -> None:
        """
        Emit the run's terminal status as an SSE event.
        """
        self._emit(
            jhhub.SseEnvelope(
                run_id=handle.run_id,
                type="run_status",
                summary=summary,
                run_status=status,
            )
        )

    def _emit(self, envelope: jhhub.SseEnvelope) -> None:
        """
        Assign a sequence, index the event, and publish it to the hub.
        """
        with self._lock:
            seq = self._seq.get(envelope.run_id, 0)
            self._seq[envelope.run_id] = seq + 1
        envelope.seq = seq
        if not envelope.at:
            envelope.at = time.iso_now()
        self._runs.index_sse(
            envelope.run_id,
            seq,
            envelope.type,
            envelope.at,
            envelope.summary,
            data=envelope.data,
            screenshot=envelope.screenshot,
        )
        self._hub.publish(envelope)

    def _set_status(self, handle: _Handle, status: mrruns.RunStatus) -> None:
        """
        Persist a run's status and mirror it onto the handle.
        """
        self._runs.update_status(handle.run_id, status)
        handle.status = status

    def _register(self, answer_id: str) -> jppendin.PendingAnswer[object]:
        """
        Register a pending answer a route later fulfils by id.
        """
        answer: jppendin.PendingAnswer[object] = jppendin.PendingAnswer(answer_id)
        with self._lock:
            self._pending[answer_id] = answer
        return answer

    def _deliver(self, answer_id: str, value: object) -> None:
        """
        Deliver a value to the worker waiting on ``answer_id``.
        """
        with self._lock:
            answer = self._pending.pop(answer_id, None)
        if answer is None:
            raise errors.NotFoundError(f"no pending answer {answer_id!r}")
        answer.set(value)

    def _broker_for(
        self, intervention_id: str
    ) -> Tuple[_Handle, escal.ControlBroker]:
        """
        Resolve the handle and broker owning an intervention id.
        """
        run_id = intervention_id.split("~", 1)[0]
        handle = self._handles.get(run_id)
        if handle is None or handle.broker is None:
            raise errors.UnknownInterventionError(intervention_id)
        if handle.iv_db_id != intervention_id:
            raise errors.UnknownInterventionError(intervention_id)
        return handle, handle.broker


def make_hub(loop: asyncio.AbstractEventLoop) -> jhhub.EventHub:
    """
    Build an event hub bound to the server's event loop.
    """
    hub = jhhub.EventHub(loop)
    return hub
