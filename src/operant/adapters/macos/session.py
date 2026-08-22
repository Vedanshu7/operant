"""
WindowSession: the shared handle to ONE window of ONE application.

Owns app/window resolution, the ephemeral ref->element map produced by
the observer, and the host-level helpers tools share (raise, foreground
check, screenshot, human-action capture, fault injection). Every tool
acts through this session, so nothing the gateway does can leave the
target window - a privacy guarantee, not an optimization.

The plain built-in exceptions here (``KeyError``, ``RuntimeError``,
``TimeoutError``) are load-bearing: the discovery loop's action-error
handling catches exactly those and feeds them back to the model.

Import as:

import operant.adapters.macos.session as mssessio
"""

from __future__ import annotations

import collections.abc
import re
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

import httpx
import mss
import mss.tools
import xa11y

import operant.domain.profile as profile

_HEALTHY_STATUSES = frozenset({200, 302})


# #############################################################################
# WindowSession
# #############################################################################


class WindowSession:
    """
    Bind to one app window and serves the tools acting on it.

    :ivar app_name: Application currently bound.
    :ivar window_title_pattern: Pattern the bound window's title must
        match.
    :ivar fault_injection: How to knock over the app's backend, when
        configured.
    :ivar refs: Ephemeral control handles from the last observation.
    """

    def __init__(
        self,
        app_name: str,
        window_title_pattern: str,
        fault_injection: Optional[profile.FaultInjection] = None,
    ) -> None:
        self.app_name = app_name
        self.window_title_pattern = window_title_pattern
        self.fault_injection = fault_injection
        self.refs: Dict[str, xa11y.Element] = {}
        self._app: Optional[xa11y.App] = None
        self._pid: Optional[int] = None
        self._capture_stop: Optional[threading.Event] = None
        self._capture_thread: Optional[threading.Thread] = None

    def bind_pid(self, pid: int) -> None:
        """
        Pin the session to a specific process.

        Required when more than one instance of the same app runs (the
        automation's dedicated Chrome alongside the user's personal
        one).
        """
        self._pid = pid
        self._app = None

    def retarget(
        self, app_name: str, window_title_pattern: str
    ) -> Tuple[str, str]:
        """
        Point the session at a different application window.

        :param app_name: The app to bind next.
        :param window_title_pattern: Its window title pattern.
        :return: The previous ``(app_name, pattern)`` so the caller can
            restore it after a nested graph completes.
        :raises ValueError: If ``app_name`` is empty.
        """
        if not app_name:
            raise ValueError("retarget requires a non-empty app name")
        previous = (self.app_name, self.window_title_pattern)
        self.app_name = app_name
        self.window_title_pattern = window_title_pattern
        self._app = None
        self._pid = None
        self.refs.clear()
        return previous

    def app(self, timeout: float = 10.0) -> xa11y.App:
        """
        Resolve the bound application, caching the handle.

        Refuses to resolve when nothing is bound yet (no pid and an
        empty app name). Otherwise ``xa11y.App.by_name("")`` matches the
        frontmost app, so an observe before any launch would read
        whatever window is in front (in bootstrap discovery, the
        operator console itself) and mistake it for the target.

        :raises RuntimeError: If no target has been launched or bound.
        """
        if self._app is None:
            if self._pid is not None:
                # Pinned to a pid: resolve that exact process.
                self._app = xa11y.App.by_pid(self._pid, timeout=timeout)
            elif self.app_name:
                # Resolve the bound app by name.
                self._app = xa11y.App.by_name(self.app_name, timeout=timeout)
            else:
                # Nothing bound yet: refuse to match the frontmost app.
                raise RuntimeError(
                    "no target bound yet; launch an app or URL first"
                )
        return self._app

    def window(self, timeout: float = 10.0) -> xa11y.Element:
        """
        Resolve the bound window, re-selecting a backgrounded tab.

        :raises TimeoutError: If no matching window appears in time.
        """
        deadline = time.monotonic() + timeout
        pattern = re.compile(self.window_title_pattern, re.IGNORECASE)
        first_pass = True
        while True:
            if not first_pass and time.monotonic() > deadline:
                raise TimeoutError(
                    f"no window matching /{self.window_title_pattern}/ "
                    f'in "{self.app_name}"'
                )
            first_pass = False
            found = self._find_window(pattern)
            if found is not None:
                return found
            time.sleep(0.4)

    def element_for(self, ref: str) -> xa11y.Element:
        """
        Return the element behind a control ref from the last observe.

        :raises KeyError: If the ref is stale or unknown.
        """
        element = self.refs.get(ref)
        if element is None:
            raise KeyError(f"stale or unknown control ref {ref} (observe again)")
        return element

    def raise_window(self) -> None:
        """
        Bring the bound window forward; best effort.
        """
        try:
            self.window(timeout=5.0).perform_action("raise")
            time.sleep(0.4)
        except xa11y.XA11yError:
            pass

    def ensure_foreground(self) -> None:
        """
        Refuse to proceed unless the target app verifiably has focus.

        Physical/keystroke input lands in the foreground app; sending it
        anywhere else would type into the wrong window. When the session
        is pinned to a pid (the automation's dedicated Chrome), both the
        activation and the foreground check go by pid: the dedicated
        browser and the user's personal one share the name "Google
        Chrome", so ``open -a`` would activate whichever instance the OS
        picks (usually the user's), and a name-only check would still
        pass while input landed in the wrong window.

        :raises RuntimeError: If the app never reaches the foreground.
        """
        if not self._foreground_target():
            raise RuntimeError("target app is not the foreground app")

    def screenshot(self, path: str) -> bool:
        """
        Capture the bound window to ``path``.

        Raises with BOTH reasons when neither capture route produced an
        image - the caller logs it; a silent gap here once left every
        discovery run blind without a trace.

        :return:``True`` when an image landed at ``path``.
        :raises RuntimeError: With both failure reasons when capture
            failed.
        """
        # xa11y.screenshot grabs the pixels under the window's bounds, so
        # the bound window must be ON TOP or an occluding window (the
        # user's own Chrome, same app name) is captured instead. This is
        # true for every run - generic or profile, browser or native -
        # so wait for the bound instance to actually be frontmost before
        # capturing. Best effort: if it never comes forward we still
        # capture rather than leave a blind gap. Observe reads the AX tree
        # and is unaffected; only the evidence pixels need this.
        self._foreground_target()
        try:
            xa11y.screenshot(element=self.window(timeout=3.0)).save_png(path)
            captured = True
        # Try the fallback before failing.
        except Exception as primary:
            captured = self._screenshot_fallback(path, primary)
        return captured

    def start_human_capture(
        self, on_action: collections.abc.Callable[[str], None]
    ) -> None:
        """
        Stream the human's UI actions during a control hand-off.
        """
        if self._capture_thread is None:
            stop = threading.Event()
            self._capture_stop = stop
            subscription = self.app().subscribe()
            self._capture_thread = threading.Thread(
                target=_pump_events,
                args=(subscription, stop, on_action),
                daemon=True,
            )
            self._capture_thread.start()

    def stop_human_capture(self) -> None:
        """
        Stop the human-action stream.
        """
        if self._capture_stop is not None:
            self._capture_stop.set()
        self._capture_thread = None
        self._capture_stop = None

    def inject_session_expiry(self) -> None:
        """
        Restart the app's backend so the server-side session dies.

        A real infrastructure event, used by the session-expiry demo.

        :raises RuntimeError: If fault injection is not configured.
        :raises TimeoutError: If the backend never comes back healthy.
        """
        fault = self.fault_injection
        if fault is None:
            raise RuntimeError(
                "fault injection is not configured for this profile"
            )
        subprocess.run(fault.restart_cmd, check=True, timeout=120)
        deadline = time.monotonic() + fault.timeout_s
        recovered = False
        while not recovered and time.monotonic() < deadline:
            if _healthy(fault.health_url):
                # Backend is serving again.
                recovered = True
            else:
                # Not yet: wait and poll again.
                time.sleep(3)
        if not recovered:
            raise TimeoutError(
                f"{fault.health_url} did not come back after restart"
            )

    def close(self) -> None:
        """
        Release the session's capture thread and refs.
        """
        self.stop_human_capture()
        self.refs.clear()

    def _foreground_target(self) -> bool:
        """
        Raise the bound instance and confirm it is frontmost, by pid.

        Shared by physical input (which must not proceed otherwise) and
        the screenshot (which needs the window on top for correct
        pixels). Returns whether the bound instance verifiably reached
        the foreground.
        """
        self._bring_forward()
        foreground = False
        try:
            target_pid = self._pid if self._pid is not None else self.app().pid
        except RuntimeError:
            target_pid = None
        if target_pid is not None:
            for _ in range(10):
                try:
                    if xa11y.App.foreground(timeout=1.0).pid == target_pid:
                        foreground = True
                        break
                except xa11y.XA11yError:
                    pass
                time.sleep(0.2)
        return foreground

    def _bring_forward(self) -> None:
        """
        Best-effort raise of the bound instance, by pid when one is pinned.

        Activating by pid (not by app name) is what keeps focus on the
        automation's dedicated Chrome rather than the user's own
        instance of the same name. Best effort: ``ensure_foreground``
        verifies the result and raises, while ``screenshot`` just wants
        the window on top and must not fail the run if activation is
        refused.
        """
        try:
            if self._pid is not None:
                # Pinned pid: activate that exact process.
                script = (
                    'tell application "System Events" to set frontmost of '
                    f"(first process whose unix id is {self._pid}) to true"
                )
                subprocess.run(
                    ["osascript", "-e", script], check=False, timeout=10
                )
            else:
                # Otherwise activate the app by name.
                subprocess.run(
                    ["open", "-a", self.app_name], check=False, timeout=10
                )
        except (subprocess.SubprocessError, OSError):
            pass
        self.raise_window()

    def _find_window(self, pattern: re.Pattern[str]) -> Optional[xa11y.Element]:
        """
        Find the matching window, re-selecting a backgrounded tab.
        """
        found = None
        try:
            app = self.app()
            for candidate in app.children():
                if candidate.role == "window" and pattern.search(
                    candidate.name or ""
                ):
                    found = candidate
                    break
            if found is None:
                # A window title tracks its ACTIVE tab; if the user switched
                # tabs in a shared window, our tab still exists - re-select
                # it.
                tab = app.locator(f'tab[name*="{self.window_title_pattern}"]')
                if tab.exists():
                    tab.first().select()
        except xa11y.XA11yError:
            # App restarted; re-resolve on the next call.
            self._app = None
        return found

    def _screenshot_fallback(self, path: str, primary: Exception) -> bool:
        """
        Grab the window's pixels with mss, raising if that also fails.
        """
        # A window-bounds grab keeps the evidence scoped to the target
        # window (the session's privacy guarantee), never the whole screen.
        try:
            bounds = self.window(timeout=3.0).bounds
            if bounds is None:
                raise RuntimeError("window reports no bounds")
            with mss.mss() as grabber:
                image = grabber.grab(
                    {
                        "left": int(bounds.x),
                        "top": int(bounds.y),
                        "width": int(bounds.width),
                        "height": int(bounds.height),
                    }
                )
                mss.tools.to_png(image.rgb, image.size, output=path)
            return True
        except Exception as fallback:
            raise RuntimeError(
                f"xa11y: {primary}; mss fallback: {fallback}"
            ) from fallback


def _healthy(url: str) -> bool:
    """
    Report whether ``url`` responds with a healthy status.
    """
    try:
        response = httpx.get(url, timeout=10, follow_redirects=False)
    except httpx.HTTPError:
        healthy = False
    else:
        healthy = response.status_code in _HEALTHY_STATUSES
    return healthy


def _pump_events(
    subscription: xa11y.Subscription,
    stop: threading.Event,
    on_action: collections.abc.Callable[[str], None],
) -> None:
    """
    Forward interesting accessibility events to ``on_action``.
    """
    interesting = {
        xa11y.EventType.VALUE_CHANGED,
        xa11y.EventType.FOCUS_CHANGED,
        xa11y.EventType.WINDOW_OPENED,
        xa11y.EventType.MENU_OPENED,
    }
    with subscription:
        while not stop.is_set():
            event = subscription.try_recv()
            if event is None:
                time.sleep(0.15)
                continue
            if event.event_type not in interesting:
                continue
            on_action(f"{event.event_type}: {_describe(event.target)}")


def _describe(target: Optional[xa11y.Element]) -> str:
    """
    Return a redaction-safe description of an event target.
    """
    if target is None:
        # No target: nothing to describe.
        described = ""
    else:
        # Redact secure fields; name role and label otherwise.
        secure = "secure" in str(target.raw.get("ax_role", "")).lower()
        label = (target.name or target.description or target.role or "").strip()
        described = f'{target.role} "{label}"' + (
            " [value REDACTED]" if secure else ""
        )
    return described
