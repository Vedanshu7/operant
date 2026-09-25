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
import operant.infra.repositories.runs as rrruns
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

    :ivar goal: the natural-language goal.
    :ivar capability_id: id to save the capability under.
    :ivar name: human-readable name; defaults to the id.
    :ivar profile_id: app profile to use; ``None`` selects bootstrap
        mode.
    :ivar tenant: tenant to run against.
    :ivar inputs: optional pre-seeded task inputs.
    :ivar screenshots: whether to send the model screenshots.
    :ivar max_turns: override the turn budget; ``None`` uses the
        configured default.
    :ivar agents: override ``single``/``multi``; ``None`` uses the
        configured default.
    :ivar seed_capability: a capability to rediscover: the run starts
        from its pinned graph and goal, and may retire edges that keep
        failing.
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
    seed_capability: Optional[str] = None


# #############################################################################
# DiscoverOutcome
# #############################################################################


@dataclasses.dataclass(frozen=True)
class DiscoverOutcome:
    """
    A committed discovery.

    :ivar capability: the saved capability.
    :ivar graph: the graph version it pins.
    :ivar profile_path: where the effective profile was written.
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

    :ivar llm: the executor's client.
    :ivar model_name: the executor's model id, for provenance.
    :ivar token_counter: counts prompt tokens for the executor's model;
        an estimate is used when ``None``.
    :ivar tracer: where model calls are traced; none when ``None``.
    :ivar scrubber: masks personal data in traced text.
    :ivar role_llms: clients for the multi-agent roles, by role name.
    :ivar role_models: model ids for those roles, for tracing.
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

    :param request: what to discover.
    :param factory: builds the run context.
    :param artifacts: capability storage.
    :param graphs: graph storage.
    :param profiles: profile storage (also the discovery base).
    :param models: the models the run talks to.
    :param secret_store: where secret references resolve.
    :param clarifier: answers the agent's clarifying question, if any.
    :param approver: answers approvals.
    :param credential_requester: asks a person for a credential.
    :param run_identifier: fixes the run id and evidence directory; the
        server passes the id it tracks the run under.
    :param should_stop: polled between turns; true cancels the run.
    :param on_context: called with the wired context before the run
        starts, so a caller can attach evidence and broker listeners.
    :return: a committed outcome, or a typed failure.
    """
    seed = (
        artifacts.get(request.seed_capability)
        if request.seed_capability
        else None
    )
    profile_id = request.profile_id or (
        seed.policy_scope.policy_id if seed is not None else None
    )
    base = profiles.get(profile_id) if profile_id else profiles.discovery_base()
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
            bootstrap=profile_id is None,
            max_turns=request.max_turns or context.settings.discovery.max_turns,
            screenshots=request.screenshots,
            clarifier=clarifier,
            approver=context.approver,
            credential_requester=credential_requester,
            known_graph=_known_graph(graphs, seed, base.vendor_id, profile_id),
            seed_goal_node=seed.goal_node if seed is not None else None,
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
            result,
            artifacts,
            graphs,
            profiles,
            bootstrap=cfg.bootstrap,
            retire=(
                _begin_rediscovery(context.settings, seed)
                if seed is not None
                else frozenset()
            ),
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


def _known_graph(
    graphs: prepos.GraphRepository,
    seed: Optional[artifact.CapabilityArtifact],
    vendor_id: str,
    profile_id: Optional[str],
) -> Optional[dmgraph.AppGraph]:
    """
    Pick the graph a run recognises screens against.

    The newest graph knows the most. A rediscovery falls back to the
    capability's pinned graph only when the newest has lost its goal.
    """
    if seed is not None:
        newest = graphs.get(seed.vendor_id)
        known = {node.id for node in newest.nodes}
        return (
            newest
            if seed.goal_node in known
            else graphs.get(seed.vendor_id, seed.graph_version)
        )
    if profile_id and graphs.exists(vendor_id):
        return graphs.get(vendor_id)
    return None


def _begin_rediscovery(
    settings: issettin.OperantSettings, seed: artifact.CapabilityArtifact
) -> collections.abc.Set[str]:
    """
    Start a rebuilt capability's track record, and find edges it may retire.

    Replays of the old path say nothing about the new one.

    :param settings: where the database lives.
    :param seed: the capability being rebuilt.
    :return: the edges that keep failing.
    """
    database = engine.Database.open(settings.paths.db_path)
    try:
        migrate.upgrade(database)
        runs = rrruns.SqlRunRepository(database)
        runs.close_samples(seed.id)
        failing = runs.edge_records.failing(seed.vendor_id)
    finally:
        database.close()
    return failing


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
    retire: collections.abc.Set[str] = frozenset(),
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
        recording, graph_store=graphs, artifact_store=artifacts, retire=retire
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
