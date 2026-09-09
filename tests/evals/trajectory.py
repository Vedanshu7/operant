"""
Trajectory metrics: how a run got there, not only whether it passed.

- Reference trajectories: the minimal ideal step sequence per scenario.
  A trial is scored by the longest in-order match against it: recall
  (reference steps covered, in order), precision (actual steps that were
  on the reference path), and efficiency (reference length / actual
  length, capped at 1).
- Verifier confusion (multi-agent only): each verifier verdict on a
  ``goal_complete`` claim is labelled a true/false accept/reject against
  ground truth - the window the verdict was made on is a success screen
  and the expected value was extracted by the end of the run.

These are metrics, never pass/fail checks, so pass rates stay comparable
across runs.

Import as:

import tests.evals.trajectory as trajecto
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Dict, FrozenSet, List, Optional, Sequence, Tuple

import tests.evals.scenes as scenes

if TYPE_CHECKING:
    import tests.evals.harness as harness

# Neutral protocol steps: required by multi-agent mode, not by the task.
_NEUTRAL = frozenset({"subgoal_done"})
# Alternatives are written "a|b": either step satisfies the reference.
_SUBMIT = "act:click:submit|act:press"
_LOGIN = (
    "request_secret",
    "request_secret",
    "act:fill:user",
    "act:fill:pass",
    _SUBMIT,
)
_FORM = (
    "declare_input",
    "declare_input",
    "declare_input",
    "act:fill:rec",
    "act:fill:amt",
    "act:select:choice",
    "act:click:go",
)
_READ = ("extract", "goal_complete")

REFERENCE: Dict[str, Tuple[str, ...]] = {
    "already_logged_in": _READ,
    "recognized_state": _READ,
    "login_uses_secret": (*_LOGIN, *_READ),
    "missing_url_clarifies": ("clarify", "act:launch", *_READ),
    "launch_url_only": ("act:launch", *_READ),
    "read_value_is_output": _READ,
    "typed_value_is_input": (*_FORM, *_READ),
    "dropdown_uses_select": (*_FORM, *_READ),
    "mutating_needs_approval": (*_FORM, *_READ),
    "denied_not_retried": (*_FORM, "give_up"),
    "transfer_flow": (*_LOGIN, "act:click:c2", *_FORM, *_READ),
    "premature_complete": (*_LOGIN, "act:click:c2", *_FORM, "give_up"),
    "long_run": (*(["act:click:next"] * 14), *_READ),
}

# Screens on which the goal counts as achieved; empty when it never can be.
SUCCESS_SCREENS: Dict[str, FrozenSet[str]] = {
    "already_logged_in": frozenset({"home"}),
    "recognized_state": frozenset({"home"}),
    "login_uses_secret": frozenset({"home"}),
    "missing_url_clarifies": frozenset({"home"}),
    "launch_url_only": frozenset({"home"}),
    "read_value_is_output": frozenset({"home"}),
    "typed_value_is_input": frozenset({"done"}),
    "dropdown_uses_select": frozenset({"done"}),
    "mutating_needs_approval": frozenset({"done"}),
    "denied_not_retried": frozenset(),
    "transfer_flow": frozenset({"done"}),
    "premature_complete": frozenset(),
    "long_run": frozenset({"p15"}),
}


def step(name: str, args: Dict[str, object]) -> str:
    """
    Name one executor tool call as a trajectory step.

    :param name: The tool name.
    :param args: Its parsed arguments.
    :return: e.g. ``act:click:submit``, ``act:launch`` or ``extract``.
    """
    if name != "act":
        # Non-UI tools are steps by name alone.
        token = name
    elif args.get("action") in ("launch", "press", "scroll"):
        # The target of these is not a control ref.
        token = f"act:{args.get('action')}"
    else:
        # click / fill / select name the control they act on.
        token = f"act:{args.get('action')}:{args.get('ref', '')}"
    return token


def steps(run: harness.EvalRun) -> List[str]:
    """
    Return the executor's steps, protocol-only steps left out.
    """
    taken = [
        step(call.name, _args(call.arguments))
        for call in run.llm.calls
        if call.name not in _NEUTRAL
    ]
    return taken


def _args(arguments: str) -> Dict[str, object]:
    """
    Parse tool arguments; empty when they are not a JSON object.
    """
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        parsed = {}
    args: Dict[str, object] = parsed if isinstance(parsed, dict) else {}
    return args


def _matches(expected: str, actual: str) -> bool:
    """
    Whether ``actual`` satisfies a reference step (with alternatives).
    """
    return actual in expected.split("|")


def in_order_match(reference: Sequence[str], actual: Sequence[str]) -> int:
    """
    Length of the longest in-order match (LCS) of actual against reference.

    :param reference: The ideal steps.
    :param actual: The steps taken.
    :return: How many reference steps were taken, in order.
    """
    rows = len(reference) + 1
    cols = len(actual) + 1
    table = [[0] * cols for _ in range(rows)]
    for i in range(1, rows):
        for j in range(1, cols):
            if _matches(reference[i - 1], actual[j - 1]):
                table[i][j] = table[i - 1][j - 1] + 1
            else:
                table[i][j] = max(table[i - 1][j], table[i][j - 1])
    return table[-1][-1]


def metrics(run: harness.EvalRun) -> Optional[Dict[str, float]]:
    """
    Score a trial's trajectory against its scenario's reference.

    :param run: The trial.
    :return: recall, precision, efficiency, in_order (1.0 when every
        reference step was taken in order), and the step counts;
        ``None`` for a scenario without a reference.
    """
    reference = REFERENCE.get(run.scenario.name)
    scored: Optional[Dict[str, float]] = None
    if reference is not None:
        taken = steps(run)
        hit = in_order_match(reference, taken)
        scored = {
            "recall": round(hit / len(reference), 3),
            "precision": round(hit / len(taken), 3) if taken else 0.0,
            "efficiency": (
                round(min(1.0, len(reference) / len(taken)), 3) if taken else 0.0
            ),
            "in_order": 1.0 if hit == len(reference) else 0.0,
            "steps": float(len(taken)),
            "reference_steps": float(len(reference)),
        }
    return scored


def _expected_value(run: harness.EvalRun) -> str:
    """
    Return the value a successful run of this scenario extracts.
    """
    screens = SUCCESS_SCREENS.get(run.scenario.name, frozenset())
    reads_home = screens == frozenset({"home"})
    value = run.scenario.skin.value if reads_home else scenes.CONFIRMATION
    return value


def verifier_confusion(run: harness.EvalRun) -> Dict[str, int]:
    """
    Label the verifier's verdicts on ``goal_complete`` claims.

    :param run: A multi-agent trial (single-agent trials have none).
    :return: Counts of true/false accepts and rejects.
    """
    screens = SUCCESS_SCREENS.get(run.scenario.name, frozenset())
    titles = {run.scenario.scene.screens[name].window_title for name in screens}
    expected = _expected_value(run)
    extracted = any(
        expected in value or value in expected
        for value in run.state.extracted.values()
        if value
    )
    counts = {
        "true_accept": 0,
        "false_accept": 0,
        "true_reject": 0,
        "false_reject": 0,
    }
    for event in run.events_of("verifier_verdict"):
        if event.get("reviewer") != "verifier" or event.get("claim") != "goal":
            continue
        achieved = event.get("window") in titles and extracted
        accepted = bool(event.get("passed"))
        label = (
            ("true" if achieved else "false") + "_accept"
            if accepted
            else ("false" if achieved else "true") + "_reject"
        )
        counts[label] += 1
    return counts


def summarize(
    rows: Sequence[Dict[str, object]],
) -> Dict[str, float]:
    """
    Average trajectory metrics and total verifier labels over result rows.

    :param rows: JSONL result rows that carry
        ``trajectory``/``verifier``.
    :return: Mean recall/precision/efficiency/in_order, plus confusion
        totals and the verifier's false-accept and false-reject rates.
    """
    scored = [
        r["trajectory"] for r in rows if isinstance(r.get("trajectory"), dict)
    ]
    out: Dict[str, float] = {}
    for key in ("recall", "precision", "efficiency", "in_order"):
        values = [float(s[key]) for s in scored]  # type: ignore[index]
        out[key] = round(sum(values) / len(values), 3) if values else 0.0
    totals = {
        "true_accept": 0,
        "false_accept": 0,
        "true_reject": 0,
        "false_reject": 0,
    }
    for row in rows:
        labels = row.get("verifier")
        if isinstance(labels, dict):
            for key in totals:
                totals[key] += int(labels.get(key, 0))
    out.update({k: float(v) for k, v in totals.items()})
    accepts = totals["true_accept"] + totals["false_accept"]
    rejects = totals["true_reject"] + totals["false_reject"]
    out["false_accept_rate"] = (
        round(totals["false_accept"] / accepts, 3) if accepts else 0.0
    )
    out["false_reject_rate"] = (
        round(totals["false_reject"] / rejects, 3) if rejects else 0.0
    )
    return out
