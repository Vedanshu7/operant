"""
SQLite schema and session management.

The engine is synchronous on purpose: replay and discovery run in worker
threads, and SQLite serialises writers anyway. HTTP handlers call the
repositories through FastAPI's thread pool.
"""
