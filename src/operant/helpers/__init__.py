"""
Shared utilities usable from any layer.

Modules here import only the standard library and third-party packages,
never other Operant packages, so nothing can depend on them in a cycle.

- ``files``: atomic JSON writes, model read/write, file locks.
- ``time``: timezone-aware clocks and ISO formatting.
- ``text``: slugs, truncation, placeholder substitution.
- ``ids``: run and record identifiers.
- ``logging``: logger factory and process-wide configuration.
"""
