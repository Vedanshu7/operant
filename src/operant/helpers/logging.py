"""Logger factory and one-call process configuration.

Typical usage example:

  import operant.helpers.logging as log
  _LOG = log.get_logger(__name__)
  _LOG.info("replayed %s in %.1fs", capability_id, elapsed)

Import as:

import operant.helpers.logging as logging
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, Literal

_ROOT = "operant"


# #############################################################################
# JsonFormatter
# #############################################################################


class JsonFormatter(logging.Formatter):
    """
    Format records as one JSON object per line.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Render ``record`` as a JSON line.

        :param record: The log record.
        :return: A JSON document with time, level, logger, and message.
        """
        payload: Dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        line = json.dumps(payload)
        return line


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger under the ``operant`` namespace.

    :param name: Usually ``__name__`` of the calling module.
    :return: The logger.
    """
    if name.startswith(_ROOT):
        # Already namespaced: take the name as given.
        logger = logging.getLogger(name)
    else:
        # Bare module name: nest it under the root namespace.
        logger = logging.getLogger(f"{_ROOT}.{name}")
    return logger


def configure(level: str = "INFO", fmt: Literal["text", "json"] = "text") -> None:
    """
    Configure the ``operant`` logger hierarchy once per process.

    :param level: Logging level name.
    :param fmt:``"text"`` for human output, ``"json"`` for line-
        delimited JSON.
    """
    root = logging.getLogger(_ROOT)
    root.setLevel(level.upper())
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        # Machine-readable: one JSON object per line.
        handler.setFormatter(JsonFormatter())
    else:
        # Human-readable: a single formatted line.
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.propagate = False
