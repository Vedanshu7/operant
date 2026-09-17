"""
Local PII scrubbing with Microsoft Presidio and a spaCy model.

Everything runs in-process: no text leaves the machine to be scrubbed.
Presidio's recognizers are joined by the value shapes the sensitivity
gates already use, so the two layers agree on what is sensitive.

Import as:

import operant.adapters.privacy.presidio as appresid
"""

from __future__ import annotations

from typing import Any, Final, List, Tuple, cast

import presidio_analyzer
import presidio_analyzer.nlp_engine as panlpeng
import presidio_anonymizer
import presidio_anonymizer.entities as paentiti

import operant.domain.sensitivity as sensv

ENTITIES: Final[Tuple[str, ...]] = (
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "US_BANK_NUMBER",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON",
    "LOCATION",
    "DATE_TIME",
)
_PATTERN_SCORE = 0.9


# #############################################################################
# PresidioScrubber
# #############################################################################


class PresidioScrubber:
    """
    Implement ``operant.ports.privacy.TextScrubber`` with Presidio.
    """

    def __init__(self, spacy_model: str, *, threshold: float = 0.5) -> None:
        """
        Load the spaCy model and register the sensitivity value shapes.

        :param spacy_model: an installed spaCy pipeline, e.g.
            ``en_core_web_lg``.
        :param threshold: minimum recognizer score to mask an entity.
        """
        nlp = panlpeng.NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": spacy_model}],
            }
        ).create_engine()
        self._analyzer = presidio_analyzer.AnalyzerEngine(
            nlp_engine=nlp, supported_languages=["en"]
        )
        for name, pattern in sensv.VALUE_PATTERNS.items():
            self._analyzer.registry.add_recognizer(
                presidio_analyzer.PatternRecognizer(
                    supported_entity=name,
                    patterns=[
                        presidio_analyzer.Pattern(
                            name=name.lower(),
                            regex=pattern.pattern,
                            score=_PATTERN_SCORE,
                        )
                    ],
                )
            )
        self._entities: List[str] = [*ENTITIES, *sensv.VALUE_PATTERNS]
        self._anonymizer = presidio_anonymizer.AnonymizerEngine()
        self._threshold = threshold

    def scrub(self, text: str) -> str:
        """
        Replace every entity found in ``text`` with ``<ENTITY_TYPE>``.
        """
        if not text.strip():
            # Nothing to analyze; skip the NLP pipeline.
            scrubbed = text
        else:
            # Analyze, then replace each finding with its typed placeholder.
            found = self._analyzer.analyze(
                text=text,
                language="en",
                entities=self._entities,
                score_threshold=self._threshold,
            )
            scrubbed = self._anonymizer.anonymize(
                text=text,
                # Presidio documents passing analyzer results here, but its
                # two packages declare separate RecognizerResult types.
                analyzer_results=cast(Any, found),
                operators={"DEFAULT": paentiti.OperatorConfig("replace")},
            ).text
        return scrubbed
