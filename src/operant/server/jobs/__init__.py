"""
Server jobs: the run manager and the thread/async plumbing it needs.

Runs are synchronous and block on human decisions, so each executes in
its own worker thread. ``PendingAnswer`` bridges a blocked worker thread
to the async HTTP route that answers it; ``EventHub`` streams a run's
evidence events to SSE subscribers; ``RunManager`` ties them together.
"""
