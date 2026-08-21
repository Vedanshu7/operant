"""
Use cases: the operations the CLI and server both invoke.

Each is a plain function over repositories and a run-context factory, so
the CLI wraps them thinly and the server calls them from its worker
threads.
"""
