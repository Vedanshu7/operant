"""
Operant: discover a UI task once with an LLM, replay it deterministically.

The package is layered: ``domain`` (pure models and decisions),
``ports`` (protocols), ``application`` (use cases), ``adapters`` (real
drivers), ``infra`` (settings, storage), ``server`` (HTTP API), ``cli``
(commands), and ``helpers`` (shared utilities). See
``docs/conventions.md``.
"""

__version__ = "0.1.0"
