"""
Run LLM discovery and commit the resulting capability.

Import as:

import operant.application.usecases.discover as discover
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, Optional, Union

import operant.application.acting as acting
import operant.application.capabilities as capab
import operant.application.context as accontex
import operant.application.discovery.config as config
import operant.application.discovery.loop as loop
import operant.application.discovery.observe as dsobserv
import operant.application.discovery.team as dsteam
import operant.application.discovery.window as dswindow
import operant.application.memory as apmemory
import operant.application.recorder.recording as recdng
import operant.application.remediation as remem
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as dmgraph
import operant.domain.profile as dmprofil
import operant.infra.db.engine as engine
import operant.infra.db.migrate as migrate
import operant.infra.repositories.memory as rmmemory
import operant.infra.repositories.remediations as rgremed
import operant.infra.settings as issettin
import operant.ports.hitl as hitl
import operant.ports.llm as plllm
import operant.ports.privacy as ppprivac
import operant.ports.repositories as prepos
import operant.ports.secrets as secrets
import operant.ports.tracing as pttracin

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
    :ivar agents: Override ``single``/``multi``; ``None`` uses the
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
    agents: Optional[str] = None


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


# #############################################################################
# ModelWiring
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ModelWiring:
    """
    The models a discovery run talks to, and where their calls are traced.

    :ivar llm: The executor's client.
    :ivar model_name: The executor's model id, for provenance.
    :ivar token_counter: Counts prompt tokens for the executor's model;
        an estimate is used when ``None``.
    :ivar tracer: Where model calls are traced; none when ``None``.
    :ivar scrubber: Masks personal data in traced text.
    :ivar role_llms: Clients for the multi-agent roles, by role name.
    :ivar role_models: Model ids for those roles, for tracing.
    """

    llm: plllm.LlmClient
    model_name: str
    token_counter: Optional[plllm.TokenCounter] = None
    tracer: Optional[pttracin.Tracer] = None
    scrubber: Optional[ppprivac.TextScrubber] = None
    role_llms: collections.abc.Mapping[str, plllm.LlmClient] = dataclasses.field(
        default_factory=dict
    )
    role_models: Dict[str, str] = dataclasses.field(default_factory=dict)


def execute_discovery(
    request: DiscoverRequest,
    *,
    factory: accontex.ContextBuilder,
    artifacts: prepos.ArtifactRepository,
    graphs: prepos.GraphRepository,
    profiles: prepos.ProfileRepository,
    models: ModelWiring,
    secret_store: secrets.SecretStore,
    clarifier: Optional[hitl.Clarifier] = None,
    approver: Optional[hitl.Approver] = None,
    credential_requester: Optional[hitl.CredentialRequester] = None,
    run_identifier: Optional[str] = None,
    should_stop: Optional[collections.abc.Callable[[], bool]] = None,
    on_context: Optional[
        collections.abc.Callable[[accontex.RunContext], None]
    ] = None,
) -> Union[DiscoverOutcome, config.DiscoveryFailure]:
    """
    Run discovery, commit the recording, and persist the profile.

    :param request: What to discover.
    :param factory: Builds the run context.
    :param artifacts: Capability storage.
    :param graphs: Graph storage.
    :param profiles: Profile storage (also the discovery base).
    :param models: The models the run talks to.
    :param secret_store: Where secret references resolve.
    :param clarifier: Answers the agent's clarifying question, if any.
    :param approver: Answers approvals.
    :param credential_requester: Asks a person for a credential.
    :param run_identifier: Fixes the run id and evidence directory; the
        server passes the id it tracks the run under.
    :param should_stop: Polled between turns; true cancels the run.
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
            agents=request.agents or context.settings.discovery.agents,
        )
        deps = loop.DiscoveryDeps(
            surface=context.surface,
            broker=context.broker,
            log=context.log,
            llm=models.llm,
            secret_store=secret_store,
            model_name=models.model_name,
            browsers=context.settings.browser.browser_app_names,
            default_browser=context.settings.browser.default_app,
            remediation=remem.RemediationMemory(
                rgremed.RemediationsStore(context.settings.paths.remediations)
            ),
            window_budget=dswindow.WindowBudget(
                keep_full_turns=context.settings.discovery.keep_full_turns,
                budget_ratio=context.settings.discovery.context_budget_ratio,
                max_tokens=context.settings.discovery.context_max_tokens,
            ),
            token_counter=models.token_counter or dswindow.EstimatedCounter(),
            tracer=models.tracer or dsobserv.NoopTracer(),
            scrubber=models.scrubber,
            role_llms=dict(models.role_llms),
            role_models=dict(models.role_models),
            team=_team_budget(context.settings.discovery),
            memory=_memory(context.settings, cfg.agents),
            # A real app loads pages after clicks; record the settled screen.
            settle=acting.SettlePolicy(),
            should_stop=should_stop or (lambda: False),
        )
        result = loop.run_discovery(cfg, deps)
    finally:
        context.close()
        if models.tracer is not None:
            models.tracer.flush()
    outcome: Union[DiscoverOutcome, config.DiscoveryFailure]
    if isinstance(result, config.DiscoveryFailure):
        outcome = result
    else:
        outcome = _commit(
            result, artifacts, graphs, profiles, bootstrap=cfg.bootstrap
        )
    return outcome


def _team_budget(config_: issettin.DiscoverySettings) -> dsteam.TeamBudget:
    """
    Build the coordinator's bounds from the discovery settings.
    """
    budget = dsteam.TeamBudget(
        max_replans=config_.max_replans,
        max_rejections_per_subgoal=config_.max_rejections_per_subgoal,
        stall_turns=config_.stall_turns,
        planner_samples=config_.planner_samples,
        extract_candidates=config_.extract_candidates,
        fanout_workers=config_.fanout_workers,
        compile_review=config_.compile_review,
    )
    return budget


def _memory(
    settings: issettin.OperantSettings, agents: str
) -> Optional[apmemory.AgentMemory]:
    """
    Open agent memory when the configured mode covers this kind of run.
    """
    memory: Optional[apmemory.AgentMemory] = None
    mode = settings.discovery.memory
    if mode == "all" or (mode == "multi" and agents == "multi"):
        database = engine.Database.open(settings.paths.db_path)
        migrate.upgrade(database)
        memory = apmemory.AgentMemory(rmmemory.SqlMemoryStore(database))
    return memory


def _commit(
    result: config.DiscoveryResult,
    artifacts: prepos.ArtifactRepository,
    graphs: prepos.GraphRepository,
    profiles: prepos.ProfileRepository,
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
        # once wiped a demo app's tenants and secret refs); give the run
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
    profiles: prepos.ProfileRepository,
    graphs: prepos.GraphRepository,
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
