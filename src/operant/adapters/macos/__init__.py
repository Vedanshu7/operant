"""
MacOS accessibility adapters: the session, tools, and gateway assembly.

Everything here needs the ``macos`` extra (xa11y, mss) and the OS
permissions the driver daemon owns. Nothing outside ``adapters.macos``
imports these modules at module scope - the factory loads them lazily so
the server process never touches xa11y.
"""
