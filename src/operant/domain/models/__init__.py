"""
Typed contracts for the whole system.

Persisted documents (graphs, capability artifacts, replay results) are
pydantic models validated on load and save. Runtime-only shapes (the
screen digest, surface actions) are frozen dataclasses and never reach
disk.

Consumers import the submodule they need, never names from here::

    from operant.domain.models import artifact
    artifact.CapabilityArtifact.model_validate(data)

Submodules:

- ``digest``: the runtime screen digest (``ScreenDigest``).
- ``targets``: ranked target strategies and parameterised ``Value``.
- ``graph``: the versioned application graph (nodes, edges, outcomes).
- ``artifact``: the capability contract pinned to a graph version.
- ``results``: the replay result contract and failure taxonomy.
- ``actions``: the runtime ``SurfaceAction`` sent to a surface.
"""
