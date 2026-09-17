"""
A GEPA adapter over the eval harness.

A candidate is a set of role prompts, its score is the share of checks a
scenario passes, and the check failures are the written feedback GEPA reflects
on.

Import as:

import tests.evals.gepa_adapter as gepaadap
"""

from __future__ import annotations

import collections.abc
import dataclasses
import itertools
import pathlib
from typing import Any, Dict, List, Mapping, Optional, Sequence

import gepa

import operant.application.discovery.agents.prompts as daprompt
import operant.application.discovery.prompt as prompt
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes

# GEPA component name -> discovery role.
COMPONENTS: Dict[str, str] = {
    "executor_prompt": "executor",
    "planner_prompt": "planner",
    "verifier_prompt": "verifier",
}
_SLOTS = ("{secret_names}", "{default_browser}")


def seed_candidate(mode: str) -> Dict[str, str]:
    """
    Return today's prompts as GEPA's starting candidate.

    :param mode: ``single`` tunes the executor; ``multi`` also tunes the
        planner and verifier.
    :return: component name -> prompt text.
    """
    seed = {"executor_prompt": prompt.SYSTEM_PROMPT_TEMPLATE}
    if mode == "multi":
        seed["planner_prompt"] = daprompt.PLANNER_PROMPT
        seed["verifier_prompt"] = daprompt.VERIFIER_PROMPT
    return seed


def candidate_problem(candidate: Mapping[str, str]) -> Optional[str]:
    """
    Explain why a candidate cannot run, or ``None`` when it can.

    :param candidate: component name -> prompt text.
    :return: the problem, phrased as feedback for the reflection model.
    """
    executor = candidate.get("executor_prompt", prompt.SYSTEM_PROMPT_TEMPLATE)
    missing = [slot for slot in _SLOTS if slot not in executor]
    problem: Optional[str] = None
    if missing:
        # Without the slots, secret names and the browser never reach it.
        problem = f"executor_prompt must keep the placeholders {missing}"
    else:
        # Any other brace breaks str.format at run time.
        try:
            executor.format(secret_names="x", default_browser="y")
        except (KeyError, IndexError, ValueError) as err:
            problem = (
                "executor_prompt must format with only {secret_names} and "
                f"{{default_browser}}; literal braces must be doubled ({err})"
            )
    if problem is None and any(not text.strip() for text in candidate.values()):
        problem = "every prompt must be non-empty"
    return problem


# #############################################################################
# OperantAdapter
# #############################################################################


class OperantAdapter:
    """
    Implement ``gepa.GEPAAdapter`` by running eval scenarios.
    """

    # GEPA's default reflective proposer writes the new texts.
    propose_new_texts = None

    def __init__(
        self, env: harness.EvalEnv, *, mode: str, work_dir: pathlib.Path
    ) -> None:
        """
        Bind the adapter to a model and a scratch directory.

        :param env: the model, secret store, tracer and scrubber.
        :param mode: the agent mode every rollout runs in.
        :param work_dir: where rollout evidence logs are written.
        """
        self._env = env
        self._mode = mode
        self._work_dir = work_dir
        self._counter = itertools.count()

    def evaluate(
        self,
        batch: List[harness.Scenario],
        candidate: Dict[str, str],
        capture_traces: bool = False,
    ) -> gepa.EvaluationBatch:
        """
        Run each scenario once with ``candidate`` and score it.
        """
        problem = candidate_problem(candidate)
        overrides = {COMPONENTS[name]: text for name, text in candidate.items()}
        outputs: List[Dict[str, Any]] = []
        scores: List[float] = []
        trajectories: List[Dict[str, Any]] = []
        objectives: List[Dict[str, float]] = []
        for scenario in batch:
            if problem is not None:
                # Unrunnable candidate: zero, with the reason as feedback.
                trajectory = _trajectory(scenario, [problem], {}, "")
                value = 0.0
            else:
                # Run it and score the share of checks that passed.
                run = harness.run_scenario(
                    self._work_dir / f"rollout-{next(self._counter)}",
                    self._env,
                    dataclasses.replace(scenario, mode=self._mode),
                    prompt_overrides=overrides,
                )
                scored = harness.score(run)
                value = sum(1 for fs in scored.values() if not fs) / len(scored)
                failures = [f"{n}: {f}" for n, fs in scored.items() for f in fs]
                traces = {"executor": run.names()}
                traces.update(
                    {
                        role: [c.name for c in rec.calls]
                        for role, rec in run.roles.items()
                        if rec.turns
                    }
                )
                trajectory = _trajectory(scenario, failures, traces, run.trace_id)
            outputs.append({"scenario": scenario.name, "score": value})
            scores.append(value)
            trajectories.append(trajectory)
            objectives.append({scenario.family: value})
        evaluated = gepa.EvaluationBatch(
            outputs=outputs,
            scores=scores,
            trajectories=trajectories if capture_traces else None,
            objective_scores=objectives,
        )
        return evaluated

    def make_reflective_dataset(
        self,
        candidate: Dict[str, str],
        eval_batch: gepa.EvaluationBatch,
        components_to_update: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Turn each rollout into Inputs / Generated Outputs / Feedback.
        """
        trajectories: Sequence[Dict[str, Any]] = eval_batch.trajectories or []
        dataset: Dict[str, List[Dict[str, Any]]] = {}
        for component in components_to_update:
            role = COMPONENTS.get(component, "executor")
            dataset[component] = [
                {
                    "Inputs": {"goal": t["goal"], "screen": t["screen"]},
                    "Generated Outputs": t["traces"].get(role, []),
                    "Feedback": "; ".join(t["failures"]) or "all checks passed",
                    "score": score,
                    "trace_id": t["trace_id"],
                }
                for t, score in zip(trajectories, eval_batch.scores)
            ]
        return dataset


def _trajectory(
    scenario: harness.Scenario,
    failures: List[str],
    traces: Dict[str, List[str]],
    trace_id: str,
) -> Dict[str, Any]:
    """
    Keep what the reflection model needs from one rollout.
    """
    start = scenario.scene.screens[scenario.scene.start]
    trajectory = {
        "scenario": scenario.name,
        "family": scenario.family,
        "goal": scenario.goal,
        "screen": f"{start.window_title}: {start.text}",
        "failures": failures,
        "traces": traces,
        "trace_id": trace_id,
    }
    return trajectory


def instances(
    families: collections.abc.Iterable[str],
) -> List[harness.Scenario]:
    """
    Return every scenario of ``families`` over every skin.

    :param families: catalog family names.
    :return: the scenarios, in catalog order.
    """
    built = [
        scenario
        for family in families
        for skin in scenes.SKINS
        for scenario in catalog.FAMILIES[family](skin)
    ]
    return built
