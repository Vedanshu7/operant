"""
Build the configured PII scrubber.

Import as:

import operant.adapters.privacy.factory as apfactor
"""

from __future__ import annotations

import importlib.util

import operant.adapters.privacy.noop as apnoop
import operant.domain.errors as errors
import operant.infra.settings as settings
import operant.ports.privacy as ppprivac


def available(spacy_model: str) -> bool:
    """
    Report whether Presidio and the spaCy model can be loaded.

    :param spacy_model: The spaCy pipeline name.
    :return: Whether the ``privacy`` extra and the model are installed.
    """
    installed = all(
        importlib.util.find_spec(name) is not None
        for name in ("presidio_analyzer", "presidio_anonymizer", "spacy")
    )
    ready = installed and importlib.util.find_spec(spacy_model) is not None
    return ready


def scrubber(config: settings.PrivacySettings) -> ppprivac.TextScrubber:
    """
    Return the scrubber for ``config.scrubber``.

    :param config: The privacy settings group.
    :return: Presidio when chosen (or available under ``auto``), else
        the no-op scrubber.
    :raises errors.ConfigError: If ``presidio`` is required but missing.
    """
    ready = available(config.spacy_model)
    if config.scrubber == "presidio" and not ready:
        raise errors.ConfigError(
            "PII scrubbing needs the privacy extra and the spaCy model "
            f"{config.spacy_model!r} (uv sync --extra privacy, then install "
            "the model wheel; see the README)"
        )
    chosen: ppprivac.TextScrubber
    if config.scrubber != "none" and ready:
        # Imported lazily: spaCy is heavy and optional.
        import operant.adapters.privacy.presidio as appresid

        chosen = appresid.PresidioScrubber(config.spacy_model)
    else:
        # Scrubbing is off, or Presidio is not installed under ``auto``.
        chosen = apnoop.NoopScrubber()
    return chosen
