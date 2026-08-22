"""
The driver daemon: the macOS gateway behind a local HTTP API.

macOS grants Accessibility / Automation per responsible app, so
actuation run from an IDE-descended process breaks when that trust goes
stale. Started once from Terminal, the daemon's grant is given once and
stays. It is also the multi-OS seam and the trusted process where the
policy choke point runs - a caller cannot bypass it by speaking HTTP. A
bearer token authenticates the loopback hop, and a daemon-side redactor
keeps secret values out of its logs.
"""
