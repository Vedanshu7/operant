"""
Resolving an edge's ``Value`` and recording extracted outputs.

``resolve_value`` turns a recorded ``Value`` (literal, param, secret
reference, or dataflow from an earlier output) into the concrete text to
type, its sensitivity class, the vendor it is being exported from when
that is not the graph being executed, and the secret reference name it
came from. Secret resolution goes through the context's ``secrets``
dict, never the environment directly. ``record_outputs`` tags outputs
with their origin and registers sensitive ones with the redactor.

Import as:

import operant.application.replay.values as values
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import operant.application.replay.context as context
import operant.application.replay.options as options
import operant.domain.errors as errors
import operant.domain.models.digest as digest
import operant.domain.models.targets as targets
import operant.domain.outcomes as outcomes
import operant.domain.sensitivity as sensv


def resolve_value(
    value: targets.Value, ctx: context.ReplayContext
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Resolve a recorded value to the text and tags an edge will use.

    :param value: The recorded value from an edge's action.
    :param ctx: The active replay context.
    :return:``(text, data_class, export_from, secret_ref)``.
        ``export_from`` names the vendor the value was extracted in when
        that is not the graph being executed (typing it here is a cross-
        app export); ``secret_ref`` names the secret reference it was
        resolved from.
    """
    resolved: Tuple[str, str, Optional[str], Optional[str]]
    if value.literal is not None:
        # A literal: use the recorded text verbatim, untagged.
        resolved = value.literal, "none", None, None
    elif value.param is not None:
        # A task input: resolve and classify its sensitivity.
        resolved = _resolve_param(value.param, ctx)
    elif value.from_output is not None:
        # A dataflow value: read from an output extracted earlier.
        resolved = _resolve_from_output(value.from_output, ctx)
    else:
        # A secret reference: resolve from the context's secrets.
        resolved = _resolve_secret(value.secret_ref, ctx)
    return resolved


def _resolve_param(
    param: str, ctx: context.ReplayContext
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Resolve a task-input value and classifies its sensitivity.
    """
    got = ctx.opts.params.get(param)
    if got is None:
        raise errors.PreconditionFailedError(
            f'missing required input parameter "{param}"'
        )
    spec = ctx.capability.inputs.get(param)
    declared: Optional[str] = None
    if spec is not None:
        declared = (
            spec.data_class
            if spec.data_class != "none"
            else ("pii" if spec.sensitive else None)
        )
    data_class = sensv.strongest(declared, sensv.classify(name=param, value=got))
    return got, data_class, None, None


def _resolve_from_output(
    name: str, ctx: context.ReplayContext
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Resolve a dataflow value extracted earlier this run.

    In a nested invoke the caller's outputs arrive through params (the
    traversal layer merges them in), so both sources are consulted.
    """
    got = ctx.outputs.get(name) or ctx.opts.params.get(name)
    if got is None:
        raise errors.PreconditionFailedError(
            f'output "{name}" was not extracted before this step'
        )
    origin = ctx.output_origins.get(name)
    data_class = (
        origin.data_class if origin else sensv.classify(name=name, value=got)
    )
    export_from = (
        origin.vendor_id
        if origin and origin.vendor_id != ctx.graph.vendor_id
        else None
    )
    return got, data_class, export_from, None


def _resolve_secret(
    secret_ref: Optional[str], ctx: context.ReplayContext
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Resolve a secret reference from the context's resolved secrets.
    """
    secret = ctx.secrets.get(secret_ref or "")
    if secret is None:
        raise errors.PreconditionFailedError(
            f'secretRef "{secret_ref}" is not resolvable from the environment'
        )
    return secret, "credential", None, secret_ref


def record_outputs(ctx: context.ReplayContext, outputs: Dict[str, str]) -> None:
    """
    Tags outputs with origin and redacts sensitive ones from now on.

    The caller still receives the values as the result; only what is
    written to evidence from this moment on is masked.

    :param ctx: The active replay context.
    :param outputs: Extracted values keyed by output name.
    """
    for name, value in outputs.items():
        spec = ctx.capability.outputs.get(name)
        data_class = sensv.strongest(
            spec.data_class if spec else None,
            sensv.classify(name=name, value=value),
        )
        ctx.output_origins[name] = options.OutputOrigin(
            vendor_id=ctx.graph.vendor_id, data_class=data_class
        )
        if sensv.is_sensitive(data_class):
            ctx.redactor.add_secret(value)
    ctx.outputs.update(outputs)


def extract_eagerly(
    ctx: context.ReplayContext, screen: digest.ScreenDigest
) -> None:
    """
    Run the capability's extraction the moment its screen is captured.

    Later ``from_output`` steps (dataflow into another app) can then
    read the values; the end-of-run block still validates completeness.

    :param ctx: The active replay context.
    :param screen: The digest captured at ``extract_at_node``.
    """
    if ctx.capability.extract:
        outputs, _missing = outcomes.run_extraction(
            ctx.capability.extract, screen
        )
        record_outputs(ctx, outputs)
