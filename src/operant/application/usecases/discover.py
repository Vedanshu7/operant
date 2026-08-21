"""
Run LLM discovery and commit the resulting capability.

Import as:

import operant.application.usecases.discover as discover
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, Optional, Union

import operant.application.capabilities as capab
import operant.application.context as accontex
import operant.application.discovery.config as config
import operant.application.discovery.loop as loop
import operant.application.recorder.recording as recdng
import operant.application.remediation as remem
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as dmgraph
import operant.domain.profile as dmprofil
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.infra.repositories.remediations as rgremed
import operant.ports.hitl as hitl
import operant.ports.llm as plllm
import operant.ports.secrets as secrets

# #############################################################################
# DiscoverRequest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class DiscoverRequest:
    """
    One discovery invocation.

    :ivar goal: The natural-language goal.
    :ivar capability_id: Id to save the capability under.
    :ivar name: Human-readable name; defaults to the id.
    :ivar profile_id: App profile to use; ``None`` selects bootstrap
        mode.
    :ivar tenant: Tenant to run against.
    :ivar inputs: Optional pre-seeded task inputs.
    :ivar screenshots: Whether to send the model screenshots.
    :ivar max_turns: Override the turn budget; ``None`` uses the
        configured default.
    """

    goal: str
    capability_id: str
    name: str = ""
    profile_id: Optional[str] = None
    tenant: str = ""
    inputs: Optional[Dict[str, str]] = None
    screenshots: bool = True
    max_turns: Optional[int] = None


# #############################################################################
# DiscoverOutcome
# #############################################################################


@dataclasses.dataclass(frozen=True)
class DiscoverOutcome:
    """
    A committed discovery.

    :ivar capability: The saved capability.
    :ivar graph: The graph version it pins.
    :ivar profile_path: Where the effective profile was written.
    """

    capability: artifact.CapabilityArtifact
    graph: dmgraph.AppGraph
    profile_path: str


def execute_discovery(
    request: DiscoverRequest,
    *,
    factory: accontex.ContextBuilder,
    artifacts: raartifa.FileArtifactRepository,
    graphs: rggraphs.FileGraphRepository,
    profiles: rpprofil.FileProfileRepository,
    llm: plllm.LlmClient,
    secret_store: secrets.SecretStore,
    model_name: str,
    clarifier: Optional[hitl.Clarifier] = None,
    approver: Optional[hitl.Approver] = None,
    credential_requester: Optional[hitl.CredentialRequester] = None,
    run_identifier: Optional[str] = None,
    on_context: Optional[
        collections.abc.Callable[[accontex.RunContext], None]
    ] = None,
) -> Union[DiscoverOutcome, config.DiscoveryFailure]:
    """
    Run discovery, commits the recording, and persists the profile.

    :param request: What to discover.
    :param factory: Builds the run context.
    :param artifacts: Capability storage.
    :param graphs: Graph storage.
    :param profiles: Profile storage (also the discovery base).
    :param llm: The model client.
    :param secret_store: Where secret references resolve.
    :param model_name: Model id for provenance.
    :param clarifier: Answers the agent's clarifying question, if any.
    :param approver: Answers approvals.
    :param run_identifier: Fixes the run id and evidence directory; the
        server passes the id it tracks the run under.
    :param on_context: Called with the wired context before the run
        starts, so a caller can attach evidence and broker listeners.
    :return: A committed outcome, or a typed failure.
    """
    base = (
        profiles.get(request.profile_id)
        if request.profile_id
        else profiles.discovery_base()
    )
    tenant = request.tenant or base.default_tenant
    context = factory.build(
        "discovery", base, approver=approver, run_identifier=run_identifier
    )
    if on_context is not None:
        on_context(context)
    try:
        cfg = config.DiscoveryConfig(
            goal=request.goal,
            capability_id=request.capability_id,
            capability_name=request.name or request.capability_id,
            inputs=dict(request.inputs or {}),
            profile=base,
            tenant=tenant,
            bootstrap=request.profile_id is None,
            max_turns=request.max_turns or context.settings.discovery.max_turns,
            screenshots=request.screenshots,
            clarifier=clarifier,
            approver=context.approver,
            credential_requester=credential_requester,
            known_graph=(
                graphs.get(base.vendor_id)
                if request.profile_id and graphs.exists(base.vendor_id)
                else None
            ),
        )
        deps = loop.DiscoveryDeps(
            surface=context.surface,
            broker=context.broker,
            log=context.log,
            llm=llm,
            secret_store=secret_store,
            model_name=model_name,
            browsers=context.settings.browser.browser_app_names,
            default_browser=context.settings.browser.default_app,
            remediation=remem.RemediationMemory(
                rgremed.RemediationsStore(context.settings.paths.remediations)
            ),
        )
        result = loop.run_discovery(cfg, deps)
    finally:
        context.close()
    outcome: Union[DiscoverOutcome, config.DiscoveryFailure]
    if isinstance(result, config.DiscoveryFailure):
        outcome = result
    else:
        outcome = _commit(
            result, artifacts, graphs, profiles, bootstrap=cfg.bootstrap
        )
    return outcome


def _commit(
    result: config.DiscoveryResult,
    artifacts: raartifa.FileArtifactRepository,
    graphs: rggraphs.FileGraphRepository,
    profiles: rpprofil.FileProfileRepository,
    *,
    bootstrap: bool,
) -> DiscoverOutcome:
    """
    Commit the discovery result, rebranding a colliding bootstrap run.
    """
    document = result.profile
    recording = result.recording
    if bootstrap and profiles.exists(document.vendor_id):
        # A generic (bootstrap) run derived the id of a profile that
        # already exists. It must never overwrite the curated one (that
        # once wiped ParaBank's tenants and secret refs); give the run
        # its own generic id and carry it onto the graph and capability
        # so profile, graph, and recording stay consistent.
        generic = _generic_id(profiles, graphs, document.vendor_id)
        recording = _rebrand_recording(recording, document.vendor_id, generic)
        document = _rebrand_profile(document, generic)
    capability, merged = capab.commit_recording(
        recording, graph_store=graphs, artifact_store=artifacts
    )
    profile_path = profiles.save(document)
    outcome = DiscoverOutcome(
        capability=capability, graph=merged, profile_path=str(profile_path)
    )
    return outcome


def _generic_id(
    profiles: rpprofil.FileProfileRepository,
    graphs: rggraphs.FileGraphRepository,
    vendor_id: str,
) -> str:
    """
    Pick a free ``<vendor>-generic`` id for a colliding bootstrap run.
    """
    base = f"{vendor_id}-generic"
    candidate = base
    suffix = 2
    while profiles.exists(candidate) or graphs.exists(candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _rebrand_profile(
    document: dmprofil.AppProfile, vendor_id: str
) -> dmprofil.AppProfile:
    """
    Return the profile under a new vendor id, policy id included.
    """
    rebranded = document.model_copy(
        update={
            "vendor_id": vendor_id,
            "policy": document.policy.model_copy(update={"id": vendor_id}),
        }
    )
    return rebranded


def _rebrand_recording(
    recording: recdng.Recording, old_id: str, vendor_id: str
) -> recdng.Recording:
    """
    Return the recording rebound to a new vendor id.
    """
    bindings = {
        node: (
            (vendor_id, host, pattern)
            if held == old_id
            else (held, host, pattern)
        )
        for node, (held, host, pattern) in recording.node_bindings.items()
    }
    scope = recording.policy_scope.model_copy(update={"policy_id": vendor_id})
    rebranded = dataclasses.replace(
        recording,
        vendor_id=vendor_id,
        node_bindings=bindings,
        policy_scope=scope,
    )
    return rebranded
