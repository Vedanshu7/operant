"""
Turning recorder state into a pure ``Recording``.

Parameterisation: input values become ``{{param}}`` templates. On
record-identified targets every retained strategy must reference the
parameter - anything else captured the discovery-time record and could
resolve to the WRONG record - and a ``RECORD_NOT_FOUND`` business-
outcome edge is synthesised. A sensitive literal that survived
parameterisation is promoted to an input: graphs are immutable, so it
must never land there.

Import as:

import operant.application.recorder.builder as builder
"""

from __future__ import annotations

import dataclasses
import re
from typing import Dict, Final, List, Optional, Set, Tuple

import operant.application.recorder.recording as recdng
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.domain.profile as dpprofil
import operant.domain.sensitivity as sensv
import operant.helpers.time as time

# #############################################################################
# _BuildState
# #############################################################################


@dataclasses.dataclass
class _BuildState:
    """
    Mutable accumulation shared by the build helpers.
    """

    params: List[Tuple[str, str]]
    inputs: Dict[str, str]
    outputs: Dict[str, str]
    edges: List[graph.Edge] = dataclasses.field(default_factory=list)
    outcome_edges: List[graph.OutcomeEdge] = dataclasses.field(
        default_factory=list
    )
    promoted: List[Tuple[str, str, str]] = dataclasses.field(default_factory=list)
    promoted_inputs: Dict[str, artifact.IoField] = dataclasses.field(
        default_factory=dict
    )


def build(
    recorder: recdng.Recorder,
    *,
    profile: dpprofil.AppProfile,
    capability_id: str,
    capability_name: str,
    goal: str,
    inputs: Dict[str, str],
    outputs: Dict[str, str],
    model: str,
    run_id: str,
    input_classes: Optional[Dict[str, str]] = None,
    output_classes: Optional[Dict[str, str]] = None,
) -> recdng.Recording:
    """
    Produce a pure ``Recording`` from the recorder's accumulated state.

    :param recorder: The recorder that observed the run.
    :param profile: The app profile the run executed under.
    :param capability_id: Id the capability will be saved under.
    :param capability_name: Human-readable name.
    :param goal: The natural-language goal.
    :param inputs: Task input values by name.
    :param outputs: Extracted output values by name.
    :param model: The model that drove discovery (or ``human-
        demonstration``).
    :param run_id: Evidence run id for provenance.
    :param input_classes: Declared sensitivity per input.
    :param output_classes: Declared sensitivity per output.
    :return: The recording, ready for ``commit_recording``.
    """
    state = _BuildState(
        params=sorted(
            ((k, v) for k, v in inputs.items() if len(v) >= 2),
            key=lambda kv: -len(kv[1]),
        ),
        inputs=inputs,
        outputs=outputs,
    )
    state.outcome_edges = list(profile.global_outcome_edges)
    for step in recorder.recorded:
        state.edges.append(_build_edge(step, state))
    nodes = list(recorder.nodes.values())
    names = _generic_output_names(outputs, state)
    extracts = [
        _parameterize_extract(spec, state).model_copy(
            update={"output": names.get(spec.output, spec.output)}
        )
        for spec in recorder.extractions
    ]
    entry = state.edges[0].from_node if state.edges else nodes[0].id
    goal_node = state.edges[-1].to_node if state.edges else nodes[0].id
    recording = recdng.Recording(
        capability_id=capability_id,
        capability_name=capability_name,
        goal=goal,
        vendor_id=profile.vendor_id,
        app_name=profile.app_name,
        window_title_pattern=profile.window_title_pattern,
        tenants=profile.tenants,
        default_tenant=profile.default_tenant,
        inputs=_require_used(
            _typed_inputs(state, input_classes or {}),
            [edge.model_dump_json() for edge in state.edges]
            + [spec.pattern for spec in extracts],
        ),
        outputs=_typed_outputs(
            {names[k]: v for k, v in outputs.items()},
            {names.get(k, k): v for k, v in (output_classes or {}).items()},
        ),
        nodes=nodes,
        edges=state.edges,
        outcome_edges=state.outcome_edges,
        entry_node=entry,
        goal_node=goal_node,
        extract_at_node=recorder.extract_node or goal_node,
        extract=extracts,
        policy_scope=artifact.PolicyScope(
            policy_id=profile.policy.id,
            required_action_kinds=sorted({e.action.kind for e in state.edges}),
            touches_mutating_edges=any(e.risk == "mutating" for e in state.edges),
        ),
        provenance=artifact.Provenance(
            discovery_run_id=run_id,
            model=model,
            recorded_at=time.iso_now(),
            goal=goal,
        ),
        node_bindings=dict(recorder.node_bindings),
        promoted=state.promoted,
    )
    return recording


def _build_edge(step: recdng.RecordedStep, state: _BuildState) -> graph.Edge:
    """
    Build one parameterised edge from a recorded step.
    """
    edge = step.edge.model_copy(deep=True)
    for name, value in state.params:
        edge.description = edge.description.replace(value, f"{{{{{name}}}}}")
    _parameterize_value(edge, step, state)
    _parameterize_option(edge, state)
    _parameterize_target(edge, step, state)
    return edge


def _parameterize_value(
    edge: graph.Edge,
    step: recdng.RecordedStep,
    state: _BuildState,
) -> None:
    """
    Rewrites a literal fill: dataflow beats params beats promotion.
    """
    value = edge.action.value
    if value is None or value.literal is None:
        return
    for name, output in state.outputs.items():
        if len(output) >= 2 and value.literal == output:
            edge.action.value = targets.Value(from_output=name)
            return
    for name, param_value in state.params:
        if value.literal == param_value:
            edge.action.value = targets.Value(param=name)
            return
    _promote_sensitive_literal(edge, step, state)


def _promote_sensitive_literal(
    edge: graph.Edge,
    step: recdng.RecordedStep,
    state: _BuildState,
) -> None:
    """
    Promote a surviving sensitive literal to an input.
    """
    value = edge.action.value
    if value is None or value.literal is None:
        return
    control = step.control
    data_class = sensv.classify(
        name=control.name if control else None,
        label=control.label if control else None,
        control_role=control.role if control else None,
        value=value.literal,
    )
    if not sensv.is_sensitive(data_class):
        return
    literal = value.literal
    taken = set(state.inputs) | set(state.promoted_inputs)
    param = _param_name(control, edge.id, taken)
    field_name = (control.name or control.label) if control else edge.id
    state.promoted_inputs[param] = artifact.IoField(
        description=(
            f'sensitive value typed into "{field_name}" '
            "(auto-promoted at recording)"
        ),
        required=False,
        sensitive=True,
        data_class=data_class,
    )
    edge.action.value = targets.Value(param=param)
    edge.description = edge.description.replace(literal, f"{{{{{param}}}}}")
    state.promoted.append((edge.id, param, data_class))


def _parameterize_option(edge: graph.Edge, state: _BuildState) -> None:
    """
    Rewrite a literal option selection into a param reference.
    """
    option = edge.action.option
    if option is None or option.literal is None:
        return
    for name, value in state.params:
        if option.literal == value:
            edge.action.option = targets.Value(param=name)
            return


def _parameterize_target(
    edge: graph.Edge,
    step: recdng.RecordedStep,
    state: _BuildState,
) -> None:
    """
    Parameterise the edge's target strategies.
    """
    if edge.target is None:
        return
    parameterized = False
    rewritten: List[targets.TargetStrategy] = []
    for strategy in edge.target.strategies:
        strategy, changed = _substitute_strategy(strategy, state.params)
        parameterized = parameterized or changed
        rewritten.append(strategy)
    if not parameterized:
        edge.target = targets.Target(
            strategies=rewritten, reasoning=edge.target.reasoning
        )
        return
    kept = [s for s in rewritten if _references_param(s)]
    edge.target = targets.Target(
        strategies=kept,
        reasoning=edge.target.reasoning
        + "; non-parameterized strategies dropped: they identified the "
        "discovery-time record",
    )
    state.outcome_edges.append(
        graph.OutcomeEdge(
            id=f"{edge.id}-record-not-found",
            at=edge.from_node,
            when=graph.TitleMatches(
                pattern=recdng.page_title_pattern(step.from_title)
            ),
            handle=graph.BusinessOutcomeHandle(
                outcome="RECORD_NOT_FOUND",
                detail=(
                    "no record matching the given input is present "
                    f"({edge.description})"
                ),
            ),
        )
    )


def _substitute_strategy(
    strategy: targets.TargetStrategy, params: List[Tuple[str, str]]
) -> Tuple[targets.TargetStrategy, bool]:
    """
    Substitute param templates into a single strategy.
    """
    changed = False
    if isinstance(strategy, targets.RoleStrategy):
        for name, value in params:
            if value in strategy.name:
                strategy = strategy.model_copy(
                    update={
                        "name": strategy.name.replace(value, f"{{{{{name}}}}}")
                    }
                )
                changed = True
    elif isinstance(strategy, targets.LabelProximityStrategy):
        for name, value in params:
            if value in strategy.anchor_text:
                strategy = strategy.model_copy(
                    update={
                        "anchor_text": strategy.anchor_text.replace(
                            value, f"{{{{{name}}}}}"
                        )
                    }
                )
                changed = True
    return strategy, changed


def _references_param(strategy: targets.TargetStrategy) -> bool:
    """
    Report whether a strategy references a parameter template.
    """
    if isinstance(strategy, targets.RoleStrategy):
        result = "{{" in strategy.name
    elif isinstance(strategy, targets.LabelProximityStrategy):
        result = "{{" in strategy.anchor_text
    else:
        result = False
    return result


def _param_name(
    control: Optional[digest.Control], edge_id: str, taken: Set[str]
) -> str:
    """
    Derive a unique input name for a promoted literal.
    """
    base = ""
    if control is not None:
        base = re.sub(
            r"[^a-z0-9]+", "_", (control.name or control.label).lower()
        ).strip("_")
    base = base or f"{edge_id.replace('-', '_')}_value"
    name, suffix = base, 2
    while name in taken:
        name, suffix = f"{base}_{suffix}", suffix + 1
    return name


def _typed_inputs(
    state: _BuildState, input_classes: Dict[str, str]
) -> Dict[str, artifact.IoField]:
    """
    Build typed input fields, including promoted literals.
    """
    declared = {
        name: artifact.IoField(
            description=f'task input "{name}" (from discovery goal)',
            required=False,
            sensitive=sensv.is_sensitive(data_class),
            data_class=data_class,
        )
        for name, data_class in (
            (
                n,
                sensv.strongest(
                    input_classes.get(n), sensv.classify(name=n, value=v)
                ),
            )
            for n, v in state.inputs.items()
        )
    }
    typed = {**declared, **state.promoted_inputs}
    return typed


_PARAM_RE: Final = re.compile(r'\{\{(\w+)\}\}|"param":\s*"(\w+)"')


def _parameterize_extract(
    spec: artifact.ExtractSpec, state: _BuildState
) -> artifact.ExtractSpec:
    """
    Replace input values inside an extraction pattern with ``{{name}}``.

    A pattern anchored on an input ("12345.*?(balance)") would otherwise
    read the same record on every replay, whatever input is passed.
    """
    pattern = spec.pattern
    for name, value in state.params:
        placeholder = f"{{{{{name}}}}}"
        pattern = pattern.replace(re.escape(value), placeholder)
        pattern = pattern.replace(value, placeholder)
    templated = spec.model_copy(update={"pattern": pattern})
    return templated


def _generic_output_names(
    outputs: Dict[str, str], state: _BuildState
) -> Dict[str, str]:
    """
    Map each output name to one without an input value inside it.

    A model reading "the balance of account 12345" tends to name the
    output ``account_12345_balance``; every replay with another account
    would then report under the discovery's account. A name keeps its
    own spelling when stripping empties it or collides with another.
    """
    names: Dict[str, str] = {}
    for name in outputs:
        generic = name
        for _, value in state.params:
            token = rf"(?<![^\W_]){re.escape(value)}(?![^\W_])"
            generic = re.sub(rf"_*{token}_*", "_", generic)
        generic = generic.strip("_")
        taken = generic in outputs or generic in names.values()
        names[name] = name if not generic or taken else generic
    return names


def _require_used(
    typed: Dict[str, artifact.IoField], texts: List[str]
) -> Dict[str, artifact.IoField]:
    """
    Mark every input a recorded step depends on as required.

    A step that types an input or locates a control by it (``{{name}}``)
    cannot run without it; requiring it lets replay refuse up front with
    a clear precondition failure instead of failing to find a control.

    :param typed: Inputs as recorded.
    :param texts: The recorded steps (as JSON) and extraction patterns.
    :return: The inputs, with those the steps use marked required.
    """
    used = {
        name
        for text in texts
        for match in _PARAM_RE.finditer(text)
        for name in match.groups()
        if name
    }
    required = {
        name: spec.model_copy(update={"required": True}) if name in used else spec
        for name, spec in typed.items()
    }
    return required


def _typed_outputs(
    outputs: Dict[str, str], output_classes: Dict[str, str]
) -> Dict[str, artifact.OutField]:
    """
    Build typed output fields from extracted values.
    """
    typed = {
        name: artifact.OutField(
            description=f"extracted {name}",
            data_class=sensv.strongest(
                output_classes.get(name),
                sensv.classify(name=name, value=value),
            ),
        )
        for name, value in outputs.items()
    }
    return typed
