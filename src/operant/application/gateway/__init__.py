"""
The OS-neutral gateway: registry, dispatcher, guard, and surface adapter.

Every actuation flows registry -> guard (policy choke point) ->
dispatcher (tool fallback chain) -> a tool. The gateway knows nothing
about macOS; the tools behind it do. The same wire format lets a driver
daemon on any OS present the identical surface.
"""
