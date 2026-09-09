"""
The multi-agent coordinator: plain code that decides which role runs.

Planner -> executor (today's loop, one subgoal at a time) -> verifier
panel. A rejected subgoal goes back to the executor with the reason; two
rejections, an executor give-up, or a stall trigger a replan; when the
replan budget is spent the run escalates to a human as before. Only the
executor touches the screen, so the recording is built exactly as in
single-agent discovery.

Import as:

import operant.application.discovery.team as dsteam
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import operant.application.discovery.agents.planner as daplanne
import operant.application.discovery.agents.reviewers as darevie
import operant.application.discovery.agents.verifier as daverifi
import operant.application.discovery.blackboard as dsblackb
import operant.application.discovery.config as config
import operant.application.discovery.tools as tools
import operant.domain.events as events
import operant.domain.models.memory as mdmemory
import operant.domain.models.plan as mdplan

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop

_NO_MATCH = "Pattern did not match"


# #############################################################################
# TeamBudget
# #############################################################################


@dataclasses.dataclass(frozen=True)
class TeamBudget:
    """
    Bounds on the multi-agent coordinator.

    :ivar max_replans: Replans before a stuck run escalates to a human.
    :ivar max_rejections_per_subgoal: Verifier rejections of one subgoal
        before a replan.
    :ivar stall_turns: Executor turns without a verified subgoal before
        a replan.
    :ivar planner_samples: Plan candidates drawn in parallel.
    :ivar extract_candidates: Regex candidates drawn in parallel when an
        extract does not match.
    :ivar fanout_workers: Upper bound on parallel role calls.
    :ivar compile_review:``"on"`` reviews the saved recording
        (advisory).
    """

    max_replans: int = 2
    max_rejections_per_subgoal: int = 2
    stall_turns: int = 6
    planner_samples: int = 1
    extract_candidates: int = 3
    fanout_workers: int = 4
    compile_review: str = "on"


# #############################################################################
# Team
# #############################################################################


class Team:
    """
    Coordinate planner, executor and verifier panel for one run.
    """

    def __init__(self, session: loop.DiscoverySession) -> None:
        self._session = session
        self.board: Optional[dsblackb.Blackboard] = None
        self._recalled: Tuple[mdmemory.PlanMemory, ...] = ()

    # ── planning ───────────────────────────────────────────────────────

    def start(self, turn: int) -> None:
        """
        Make the first plan before the executor's first turn.
        """
        memory = self._recall()
        plan, _ = daplanne.propose(self._session, turn=turn, memory=memory)
        self.board = dsblackb.Blackboard(
            plan=plan,
            progress_turn=turn,
            subgoal_start=len(self._session.state.messages),
        )
        self._announce(plan, attempt=0)

    def before_turn(self, turn: int) -> None:
        """
        Fold a verified subgoal's turns away, and replan on a stall.
        """
        board = self._board()
        state = self._session.state
        if board.pending_compaction is not None:
            # Whole turns only: the cut never splits a call from its reply.
            del state.messages[board.pending_compaction :]
            board.pending_compaction = None
            board.subgoal_start = len(state.messages)
        stalled = turn - board.progress_turn >= self._budget.stall_turns
        if stalled and board.replans < self._budget.max_replans:
            # Seen as a note in the next turn's plan block.
            self._replan(
                f"no subgoal verified in {self._budget.stall_turns} turns", turn
            )

    def executor_block(self) -> str:
        """
        Return the plan context for this executor turn.
        """
        return self._board().executor_block()

    def note_step(
        self, tool: str, args: Dict[str, Any], reply: Optional[str], turn: int
    ) -> None:
        """
        Record one executor step for the reviewers.
        """
        intent = str(
            args.get("intent") or args.get("name") or args.get("ref") or ""
        )
        first = (reply or "").splitlines()[0] if reply else ""
        if tool == "act" and first.startswith("OK"):
            # A UI action that worked is progress, even before a check.
            self._board().progress_turn = turn
        self._board().steps.append(
            dsblackb.StepNote(turn=turn, tool=tool, intent=intent, result=first)
        )

    # ── tool interceptions ─────────────────────────────────────────────

    def on_subgoal_done(
        self, args: Dict[str, Any], turn: int
    ) -> tools.ToolOutcome:
        """
        Have the panel verify the active subgoal before moving on.
        """
        board = self._board()
        if board.current is None:
            outcome = tools.ToolOutcome(
                "Every subgoal is already verified - call goal_complete."
            )
        else:
            outcome = self._verify(
                str(args.get("summary", "")), turn, claim="subgoal"
            ) or (tools.ToolOutcome(self._advanced_reply()))
        return outcome

    def on_goal_complete(
        self, args: Dict[str, Any], turn: int
    ) -> tools.ToolOutcome:
        """
        Verify the goal's outcome (the last subgoal); finish when it holds.

        Intermediate subgoals the executor did not report one by one
        cannot be checked from the final screen (a filled field is gone
        once the form is submitted), so a goal claim jumps to the last
        subgoal and counts the skipped ones as covered by that final
        check.
        """
        board = self._board()
        self._skip_to_last_subgoal()
        rejected = (
            self._verify(str(args.get("summary", "")), turn, claim="goal")
            if board.current is not None
            else None
        )
        if rejected is not None:
            # The panel did not confirm the claim.
            outcome = rejected
        elif board.current is not None:
            # Verified, but the plan has more subgoals.
            outcome = tools.ToolOutcome(
                "That subgoal is verified, but the goal is not finished. "
                + self._advanced_reply()
            )
        else:
            # Everything verified: finish exactly as single-agent does.
            outcome = tools.handle_goal_complete(self._session, args, turn)
            self._after_finish(outcome, turn)
        return outcome

    def on_give_up(
        self, args: Dict[str, Any], turn: int, screenshot: str
    ) -> tools.ToolOutcome:
        """
        Replan before escalating; escalate once replans are spent.
        """
        board = self._board()
        reason = str(args.get("reason", ""))
        if board.replans < self._budget.max_replans:
            # A fresh plan may route around the blocker.
            outcome = tools.ToolOutcome(
                self._replan(f"executor gave up: {reason}", turn)
            )
        else:
            # Out of replans: hand over to a person as single-agent does.
            outcome = tools.handle_give_up(self._session, args, screenshot)
            self._learn_from_human(outcome, reason)
            self._count_failure(outcome)
        return outcome

    def on_extract(
        self, args: Dict[str, Any], outcome: tools.ToolOutcome, turn: int
    ) -> tools.ToolOutcome:
        """
        When an extract misses, try regex candidates proposed in parallel.
        """
        name = str(args.get("name", ""))
        repaired = outcome
        if outcome.reply is not None and outcome.reply.startswith(_NO_MATCH):
            pattern = darevie.extract_candidates(
                self._session, name, str(args.get("pattern", "")), turn=turn
            )
            if pattern is not None:
                retried = tools.handle_extract(
                    self._session, {"name": name, "pattern": pattern}
                )
                repaired = tools.ToolOutcome(
                    f"Your pattern did not match; a reviewed pattern did: "
                    f"{retried.reply}"
                )
        return repaired

    def _skip_to_last_subgoal(self) -> None:
        """
        Move past unreported intermediate subgoals to the last one.
        """
        board = self._board()
        while board.current is not None and not board.is_last:
            board.done.append(
                (board.current.description, "covered by the final check")
            )
            board.active += 1

    @property
    def _budget(self) -> TeamBudget:
        return self._session.deps.team

    def _recall(self) -> str:
        """
        Render recalled plans and lessons for the planner, if any.
        """
        memory = self._session.deps.memory
        text = ""
        if memory is not None:
            vendor = self._session.cfg.profile.vendor_id
            recalled = memory.recall(vendor, self._session.cfg.goal)
            text = recalled.render()
            self._recalled = recalled.plans
            self._session.log.emit(
                events.MemoryRecalled(
                    plans=len(recalled.plans),
                    lessons=len(recalled.lessons),
                    summary=(
                        f"recalled {len(recalled.plans)} plan(s) and "
                        f"{len(recalled.lessons)} lesson(s)"
                    ),
                )
            )
        return text

    def _announce(self, plan: mdplan.Plan, *, attempt: int) -> None:
        """
        Log a new plan and the subgoal the executor starts on.
        """
        log = self._session.log
        log.emit(
            events.PlanProposed(
                subgoals=[
                    {
                        "id": s.id,
                        "description": s.description,
                        "success_criteria": s.success_criteria,
                    }
                    for s in plan.subgoals
                ],
                credential_names=plan.credential_names,
                attempt=attempt,
                summary=f"plan with {len(plan.subgoals)} subgoal(s)",
            )
        )
        self._started()

    def _started(self) -> None:
        """
        Log the active subgoal, when there is one.
        """
        current = self.board.current if self.board is not None else None
        if current is not None:
            self._session.log.emit(
                events.SubgoalStarted(
                    subgoal=current.id,
                    description=current.description,
                    summary=f"subgoal {current.id}: {current.description}",
                )
            )

    def _replan(self, reason: str, turn: int) -> str:
        """
        Ask for a new plan for the remaining work; return the reply text.
        """
        board = self._board()
        board.replans += 1
        self._session.log.emit(
            events.Replanned(
                reason=reason,
                attempt=board.replans,
                summary=f"replan {board.replans}: {reason}",
            )
        )
        plan, _ = daplanne.propose(
            self._session, turn=turn, reason=reason, memory=self._recall()
        )
        board.plan = plan
        board.active = 0
        board.rejections = {}
        board.progress_turn = turn
        self._announce(plan, attempt=board.replans)
        reply = f"A NEW PLAN was made ({reason}).\n{board.executor_block()}"
        return reply

    # ── per-turn hooks ─────────────────────────────────────────────────

    def _board(self) -> dsblackb.Blackboard:
        """
        Return the blackboard; the plan exists once ``start`` ran.
        """
        if self.board is None:
            raise RuntimeError("the team has not planned yet")
        return self.board

    # ── verification ───────────────────────────────────────────────────

    def _verify(
        self, summary: str, turn: int, *, claim: str
    ) -> Optional[tools.ToolOutcome]:
        """
        Run the panel; return a rejection reply, or advance and return ``None``
        when every member passes.

        :param summary: The executor's summary of what it achieved.
        :param turn: The executor turn of the claim.
        :param claim:``subgoal`` or ``goal`` - which tool made the claim,
            logged so evals can score the verifier against the screen.
        """
        screen = self._session.state.screen
        window = screen.window_title if screen is not None else ""
        board = self._board()
        subgoal = board.current
        if subgoal is None:
            raise RuntimeError("nothing to verify: every subgoal is done")
        verdicts = daverifi.review(self._session, subgoal, turn=turn)
        for verdict in verdicts:
            self._session.log.emit(
                events.VerifierVerdict(
                    subgoal=subgoal.id,
                    passed=verdict.passed,
                    reason=verdict.reason,
                    reviewer=verdict.reviewer,
                    claim=claim,
                    window=window,
                    summary=(
                        f"{verdict.reviewer}: {subgoal.id} "
                        f"{'passed' if verdict.passed else 'rejected'}"
                    ),
                )
            )
        failed = [v for v in verdicts if not v.passed]
        rejection: Optional[tools.ToolOutcome] = None
        if failed:
            # Send the reasons back, or replan / escalate when repeated.
            rejection = self._rejected(subgoal, failed, turn)
        else:
            # Passed: fold the subgoal's turns away next turn and move on.
            board.done.append((subgoal.description, summary or "done"))
            board.active += 1
            board.progress_turn = turn
            board.pending_compaction = board.subgoal_start
            self._started()
        return rejection

    def _rejected(
        self,
        subgoal: mdplan.Subgoal,
        failed: List[mdplan.Verdict],
        turn: int,
    ) -> tools.ToolOutcome:
        """
        Handle a panel rejection of ``subgoal``.
        """
        board = self._board()
        reasons = "; ".join(f"{v.reviewer}: {v.reason}" for v in failed)
        count = board.rejections.get(subgoal.id, 0) + 1
        board.rejections[subgoal.id] = count
        memory = self._session.deps.memory
        if memory is not None:
            memory.record_lesson(
                self._session.cfg.profile.vendor_id,
                self._session.cfg.goal,
                f"'{subgoal.description}' was not done when claimed: {reasons}",
                source="verifier",
                safe=self._session.safe_text,
            )
        if count < self._budget.max_rejections_per_subgoal:
            # Keep going on the same subgoal with the reviewers' reasons.
            outcome = tools.ToolOutcome(
                f"NOT VERIFIED - {reasons}. Keep working on {subgoal.id} "
                "from the current screen."
            )
        elif board.replans < self._budget.max_replans:
            # Rejected repeatedly: a different plan may work.
            outcome = tools.ToolOutcome(
                self._replan(
                    f"{subgoal.id} rejected {count} times: {reasons}", turn
                )
            )
        else:
            # Nothing left to try automatically: escalate to a person.
            outcome = tools.handle_give_up(
                self._session,
                {"reason": f"{subgoal.id} could not be verified: {reasons}"},
                "",
            )
            self._count_failure(outcome)
        return outcome

    def _count_failure(self, outcome: tools.ToolOutcome) -> None:
        """
        Count a failure for recalled plans when the run ends escalated.
        """
        memory = self._session.deps.memory
        if memory is not None and outcome.finished is not None:
            memory.record_failure(self._recalled)

    def _advanced_reply(self) -> str:
        """
        Tell the executor the subgoal passed and what is next.
        """
        board = self._board()
        nxt = board.current
        reply = (
            f"VERIFIED. Next: subgoal {nxt.id}: {nxt.description}."
            if nxt is not None
            else "VERIFIED. Every subgoal is done - call goal_complete now."
        )
        return reply

    # ── after the run ──────────────────────────────────────────────────

    def _after_finish(self, outcome: tools.ToolOutcome, turn: int) -> None:
        """
        Review the saved recording and remember the plan that worked.
        """
        result = outcome.finished
        if isinstance(result, config.DiscoveryResult):
            if self._budget.compile_review == "on":
                darevie.review_recording(
                    self._session, result.recording, turn=turn
                )
            memory = self._session.deps.memory
            if memory is not None:
                memory.record_plan(
                    self._session.cfg.profile.vendor_id,
                    self._session.cfg.goal,
                    self._board().plan,
                    safe=self._session.safe_text,
                )

    def _learn_from_human(self, outcome: tools.ToolOutcome, reason: str) -> None:
        """
        Keep an operator's note from an intervention as a lesson.
        """
        memory = self._session.deps.memory
        note = outcome.reply or ""
        if memory is not None and outcome.finished is None and "Note:" in note:
            memory.record_lesson(
                self._session.cfg.profile.vendor_id,
                self._session.cfg.goal,
                f"stuck on '{reason}'; a person helped: {note}",
                source="human",
                safe=self._session.safe_text,
            )
