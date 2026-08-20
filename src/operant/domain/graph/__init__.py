"""
Pure algorithms over the application graph.

Submodules:

- ``pathfind``: deterministic shortest path and compiled-path resolution.
- ``merge``: fold a recorded flow into the shared graph, deduplicating
  nodes by screen identity and edges by action signature.
- ``split``: extract a node set into its own graph linked by an invoke
  edge.
- ``localize``: find which node the live screen is on.

Consumers import the submodule they need::

    from operant.domain.graph import pathfind
    pathfind.shortest_path(app_graph, "login", "overview")
"""
