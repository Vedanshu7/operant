"""
PII scrubber tests.

The factory picks the right scrubber, and Presidio masks names and
account data when the spaCy model is installed.
"""

from __future__ import annotations

import pytest

import operant.adapters.privacy.factory as apfactor
import operant.adapters.privacy.noop as apnoop
import operant.domain.errors as errors
import operant.infra.settings as settings

_SMALL_MODEL = "en_core_web_sm"


def test_none_picks_the_noop_scrubber() -> None:
    chosen = apfactor.scrubber(settings.PrivacySettings(scrubber="none"))
    assert isinstance(chosen, apnoop.NoopScrubber)


def test_auto_without_the_model_falls_back_to_noop() -> None:
    config = settings.PrivacySettings(
        scrubber="auto", spacy_model="no_such_model"
    )
    assert isinstance(apfactor.scrubber(config), apnoop.NoopScrubber)


def test_required_presidio_without_the_model_is_a_config_error() -> None:
    config = settings.PrivacySettings(
        scrubber="presidio", spacy_model="no_such_model"
    )
    with pytest.raises(errors.ConfigError):
        apfactor.scrubber(config)


@pytest.mark.privacy
@pytest.mark.skipif(
    not apfactor.available(_SMALL_MODEL), reason=f"{_SMALL_MODEL} not installed"
)
def test_presidio_masks_names_and_account_data() -> None:
    config = settings.PrivacySettings(
        scrubber="presidio", spacy_model=_SMALL_MODEL
    )
    text = (
        "Welcome back, Jordan Lee. IBAN DE89370400440532013000, "
        "SSN 123-45-6789. Click Transfer Funds."
    )
    scrubbed = apfactor.scrubber(config).scrub(text)
    assert "Jordan" not in scrubbed
    assert "DE89370400440532013000" not in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "<PERSON>" in scrubbed
