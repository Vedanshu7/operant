"""
The LLM discovery loop: observe -> decide -> act, recorded as it goes.

``config`` holds the typed contract, ``prompt`` the system prompt and
tool schemas, ``state`` the per-run accumulation, ``tools`` one handler
per model tool, ``loop`` the session that drives them, and ``bootstrap``
the vendor derivation for goal-only runs with nothing pre-seeded.
"""
