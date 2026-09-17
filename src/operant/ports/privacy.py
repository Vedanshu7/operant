"""
The PII-scrubbing port.

Mask personal data in free text before it leaves the process or is stored.

Import as:

import operant.ports.privacy as ppprivac
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# #############################################################################
# TextScrubber
# #############################################################################


@runtime_checkable
class TextScrubber(Protocol):
    """
    Replace personal data in text with typed placeholders.
    """

    def scrub(self, text: str) -> str:
        """
        Mask every personal-data entity found in ``text``.

        :param text: free text, e.g. a rendered screen digest.
        :return: the text with entities replaced, e.g. ``<PERSON>``.
        """
        ...
