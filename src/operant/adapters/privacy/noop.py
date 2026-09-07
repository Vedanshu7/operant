"""
A scrubber that changes nothing, for when Presidio is not installed.

Import as:

import operant.adapters.privacy.noop as apnoop
"""

from __future__ import annotations

# #############################################################################
# NoopScrubber
# #############################################################################


class NoopScrubber:
    """
    Implement ``operant.ports.privacy.TextScrubber`` as the identity.
    """

    def scrub(self, text: str) -> str:
        """
        Return ``text`` unchanged.
        """
        return text
