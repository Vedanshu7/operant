"""
The actuation surface port: the heterogeneity seam.

Implementations: the in-process gateway surface and the driver-daemon
client. This is the full contract callers rely on; no ``hasattr``
probing. Every action goes through the policy guard underneath.

Import as:

import operant.ports.surface as pssurfac
"""

from __future__ import annotations

import collections.abc
import pathlib
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

import operant.domain.models.actions as actions
import operant.domain.models.digest as digest

if TYPE_CHECKING:
    import operant.domain.approval as daapprov


# #############################################################################
# Surface
# #############################################################################


@runtime_checkable
class Surface(Protocol):
    """
    Observe and acts on one application window.
    """

    def snapshot(self) -> digest.ScreenDigest:
        """
        Observe the bound window.

        :return: The current screen digest.
        """
        ...

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> object:
        """
        Execute one action through the policy guard.

        :param action: The resolved action.
        :param approval: Single-use nonce from a granted approval, when
            the action was previously gated.
        :return: Implementation-specific dispatch outcome; callers treat
            it as opaque evidence.
        """
        ...

    def screenshot(self, path: pathlib.Path) -> bool:
        """
        Write a PNG of the bound window to ``path``.

        :return: Whether an image was produced.
        """
        ...

    def retarget(
        self, app_name: str, window_title_pattern: str
    ) -> Tuple[str, str]:
        """
        Rebinds the session to another application window.

        :param app_name: OS application to bind.
        :param window_title_pattern: Regex the window title must match.
        :return: The previous ``(app_name, window_title_pattern)`` so
            the caller can retarget back.
        """
        ...

    def target_text_for(self, ref: Optional[str]) -> str:
        """
        Describe the control behind a digest handle for policy text.

        :return: Name and label of the control, or ``""`` when unknown.
        """
        ...

    def start_human_capture(
        self, on_action: collections.abc.Callable[[str], None]
    ) -> None:
        """
        Start streaming the human's input actions during a hand-off.

        :param on_action: Called with a one-line description per action.
        """
        ...

    def stop_human_capture(self) -> None:
        """
        Stop the stream started by ``start_human_capture``.
        """
        ...

    def start_capture(
        self,
        out_dir: pathlib.Path,
        task: str,
        window: Optional[collections.abc.Mapping[str, Optional[str]]],
        *,
        video: bool = True,
    ) -> bool:
        """
        Start full UI-activity capture (screen, input, window).

        :param out_dir: Directory the capture is written to.
        :param task: Label stored with the capture.
        :param window: Window filter, e.g. ``{"owner": app, "title":
            None}``.
        :param video: Whether to record screen video.
        :return: Whether capture started; ``False`` when unsupported.
        """
        ...

    def stop_capture(self) -> collections.abc.Mapping[str, Any]:
        """
        Stop full capture.

        :return: The capture summary (``dir``, ``summary.action_count``,
            ``summary.video``), or empty when nothing was captured.
        """
        ...

    def grant_scope(self, grant: daapprov.ScopeGrant) -> None:
        """
        Widens the policy allowlists for the rest of the run.
        """
        ...

    def inject_session_expiry(self) -> None:
        """
        Test hook: forces the application session to expire.
        """
        ...

    def close(self) -> None:
        """
        Release the session; the surface is unusable afterwards.
        """
        ...
