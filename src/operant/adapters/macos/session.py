"""
WindowSession: the shared handle to ONE window of ONE application.

Owns app/window resolution, the ephemeral ref->element map produced by
the observer, and the host-level helpers tools share (raise, foreground
check, screenshot, human-action capture, fault injection). Every tool
acts through this session, so nothing the gateway does can leave the
target window - a privacy guarantee, not an optimization.

A failed host operation raises ``errors.DriverError`` (or
``TimeoutError`` when the backend never recovers): the discovery loop
catches those and feeds them back to the model.

Import as:

import operant.adapters.macos.session as mssessio
"""

from __future__ import annotations

import collections.abc
import ctypes
import functools
import re
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

import httpx
import mss
import mss.tools
import xa11y

import operant.domain.errors as errors
import operant.domain.profile as profile

_HEALTHY_STATUSES = frozenset({200, 302})
SCREEN_LOCKED = (
    "the screen is locked: macOS hides every app window from "
    "accessibility until someone unlocks it"
)
PERSON_ACTIVE = (
    "a person kept using the mouse or keyboard, so the run stopped "
    "rather than act under them"
)
_CF_UTF8 = 0x08000100
# `kCGEventSourceStateHIDSystemState` counts physical input only, never the
# events this process posts; `kCGAnyInputEventType` is every input type.
_HID_SYSTEM_STATE = 1
_ANY_INPUT_EVENT = 0xFFFFFFFF
# A person counts as done once the mouse and keyboard rest this long.
_PERSON_IDLE_S = 3.0
_PERSON_WAIT_S = 120.0
_PERSON_POLL_S = 0.5
# Pauses that let the window server catch up after a lookup or a raise.
_WINDOW_POLL_S = 0.4
_RAISE_SETTLE_S = 0.4
_WINDOW_TIMEOUT_S = 5.0
_SNAPSHOT_TIMEOUT_S = 3.0
_URL_TIMEOUT_S = 1.0
# Timeouts in a row before a slow app stops being asked for its address.
_URL_MAX_TIMEOUTS = 3
# AppleScript's error when macOS has not granted Automation.
_NOT_AUTHORIZED = "-1743"
# Browsers that answer AppleScript for their address; others report none.
_TAB_URL_APPS = frozenset(
    {"google chrome", "chromium", "arc", "brave browser", "microsoft edge"}
)
# Bringing the app forward: polls of the frontmost app, and the helpers'
# own time limit.
_FOREGROUND_TRIES = 10
_FOREGROUND_POLL_S = 0.2
_FOREGROUND_LOOKUP_S = 1.0
_HELPER_TIMEOUT_S = 10
# Fault injection restarts the backend, then polls until it serves again.
_RESTART_TIMEOUT_S = 120
_HEALTH_POLL_S = 3.0
_HEALTH_TIMEOUT_S = 10
_CAPTURE_POLL_S = 0.15


# #############################################################################
# WindowSession
# #############################################################################


class WindowSession:
    """
    Bind to one app window and serves the tools acting on it.

    :ivar app_name: application currently bound.
    :ivar window_title_pattern: pattern the bound window's title must
        match.
    :ivar fault_injection: how to knock over the app's backend, when
        configured.
    :ivar refs: ephemeral control handles from the last observation.
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
        self._url_refused = False
        self._url_timeouts = 0

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

        :param app_name: the app to bind next.
        :param window_title_pattern: its window title pattern.
        :return: the previous ``(app_name, pattern)`` so the caller can
            restore it after a nested graph completes.
        :raises errors.DriverError: if ``app_name`` is empty.
        """
        if not app_name:
            raise errors.DriverError("Retarget needs a non-empty app name")
        previous = (self.app_name, self.window_title_pattern)
        self.app_name = app_name
        self.window_title_pattern = window_title_pattern
        self._app = None
        self._url_refused = False
        self._url_timeouts = 0
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

        :raises RuntimeError: if no target has been launched or bound.
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
                raise errors.DriverError(
                    "No target bound yet; launch an app or URL first"
                )
        return self._app

    def window(self, timeout: float = 10.0) -> xa11y.Element:
        """
        Resolve the bound window, re-selecting a backgrounded tab.

        :raises TimeoutError: if no matching window appears in time.
        """
        if screen_locked():
            # Nothing is reachable; searching would only walk a hollow tree.
            raise TimeoutError(SCREEN_LOCKED)
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
            time.sleep(_WINDOW_POLL_S)

    def close_stale_tabs(self) -> int:
        """
        Close this app's background tabs in the bound browser.

        Re-launching an app in the automation's browser opens it in a
        new tab; without this, every run leaves another copy behind.
        Only unselected tabs whose title matches this app's pattern
        close, so another app's tab (a cross-app capability may switch
        back to it) is left alone.

        :return: how many tabs were closed.
        """
        pattern = re.compile(self.window_title_pattern, re.IGNORECASE)
        closed = 0
        try:
            for tab in self.app().locator("tab").elements():
                if tab.selected or not pattern.search(tab.name or ""):
                    continue
                button = next(
                    (
                        child
                        for child in tab.children()
                        if child.role == "button"
                        and (child.name or "").lower() == "close"
                    ),
                    None,
                )
                if button is not None:
                    button.press()
                    closed += 1
        except xa11y.XA11yError:
            # App restarted; re-resolve on the next call.
            self._app = None
        return closed

    def page_url(self, window_title: str) -> Optional[str]:
        """
        Return the address of the bound window, when the app reports one.

        macOS exposes no address through the accessibility tree that
        ``xa11y`` reads, so a browser is asked with AppleScript. AppleScript
        finds an app by name, and that can be the person's own browser
        rather than Operant's, so the window is matched by title. A page
        sets its own title, so the title is passed as an argument and never
        becomes part of the script.

        :param window_title: the bound window's accessibility title.
        :return: the address; ``None`` without an answer.
        """
        lines = _url_script(self.app_name)
        if lines is None or self._url_refused:
            return None
        page = window_title.split(f" - {self.app_name}", 1)[0]
        command = ["osascript"]
        for line in lines:
            command += ["-e", line]
        try:
            done = subprocess.run(
                [*command, "--", page],
                capture_output=True,
                text=True,
                check=False,
                timeout=_URL_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            self._url_timeouts += 1
            self._url_refused = self._url_timeouts >= _URL_MAX_TIMEOUTS
            return None
        self._url_timeouts = 0
        self._url_refused = _NOT_AUTHORIZED in done.stderr
        url = done.stdout.strip() if done.returncode == 0 else ""
        return url or None

    def element_for(self, ref: str) -> xa11y.Element:
        """
        Return the element behind a control ref from the last observe.

        :raises errors.DriverError: if the ref is stale or unknown.
        """
        element = self.refs.get(ref)
        if element is None:
            raise errors.DriverError(
                f"Stale or unknown control ref '{ref}' (observe again)"
            )
        return element

    def wait_for_person_idle(self) -> None:
        """
        Hold the next action while a person is using the mouse or keyboard.

        An action taken under someone's hands clicks where they are
        pointing or types into what they are typing in, so the run waits
        until the input rests.

        :raises errors.DriverError: with ``PERSON_ACTIVE`` if the person
            is still active after the wait.
        """
        deadline = time.monotonic() + _PERSON_WAIT_S
        while seconds_since_person_input() < _PERSON_IDLE_S:
            if time.monotonic() > deadline:
                raise errors.DriverError(PERSON_ACTIVE)
            time.sleep(_PERSON_POLL_S)

    def raise_window(self) -> None:
        """
        Bring the bound window forward; best effort.
        """
        try:
            self.window(timeout=_WINDOW_TIMEOUT_S).perform_action("raise")
            time.sleep(_RAISE_SETTLE_S)
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

        :raises errors.DriverError: if the app never reaches the
            foreground.
        """
        if not self._foreground_target():
            raise errors.DriverError("The target app is not the foreground app")

    def screenshot(self, path: str) -> bool:
        """
        Capture the bound window to ``path``.

        Raises with BOTH reasons when neither capture route produced an
        image - the caller logs it; a silent gap here once left every
        discovery run blind without a trace.

        :return: ``True`` when an image landed at ``path``.
        :raises RuntimeError: with both failure reasons when capture
            failed.
        """
        # `xa11y.screenshot` grabs the pixels under the window's bounds, so
        # the bound window must be ON TOP or an occluding window (the
        # user's own Chrome, same app name) is captured instead. This is
        # true for every run - generic or profile, browser or native -
        # so wait for the bound instance to actually be frontmost before
        # capturing. Best effort: if it never comes forward we still
        # capture rather than leave a blind gap. Observe reads the AX tree
        # and is unaffected; only the evidence pixels need this.
        self._foreground_target()
        try:
            xa11y.screenshot(
                element=self.window(timeout=_SNAPSHOT_TIMEOUT_S)
            ).save_png(path)
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

        :raises RuntimeError: if fault injection is not configured.
        :raises TimeoutError: if the backend never comes back healthy.
        """
        fault = self.fault_injection
        if fault is None:
            raise errors.DriverError(
                "Fault injection is not configured for this profile"
            )
        subprocess.run(fault.restart_cmd, check=True, timeout=_RESTART_TIMEOUT_S)
        deadline = time.monotonic() + fault.timeout_s
        recovered = False
        while not recovered and time.monotonic() < deadline:
            if _healthy(fault.health_url):
                # Backend is serving again.
                recovered = True
            else:
                # Not yet: wait and poll again.
                time.sleep(_HEALTH_POLL_S)
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
        except (errors.DriverError, RuntimeError):
            target_pid = None
        if target_pid is not None:
            for _ in range(_FOREGROUND_TRIES):
                try:
                    if (
                        xa11y.App.foreground(timeout=_FOREGROUND_LOOKUP_S).pid
                        == target_pid
                    ):
                        foreground = True
                        break
                except xa11y.XA11yError:
                    pass
                time.sleep(_FOREGROUND_POLL_S)
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
                    ["osascript", "-e", script],
                    check=False,
                    timeout=_HELPER_TIMEOUT_S,
                )
            else:
                # Otherwise activate the app by name.
                subprocess.run(
                    ["open", "-a", self.app_name],
                    check=False,
                    timeout=_HELPER_TIMEOUT_S,
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
            bounds = self.window(timeout=_SNAPSHOT_TIMEOUT_S).bounds
            if bounds is None:
                raise errors.DriverError("The window reports no bounds")
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
            raise errors.DriverError(
                f"xa11y: {primary}; mss fallback: {fallback}"
            ) from fallback


def _url_script(app_name: str) -> Optional[Tuple[str, ...]]:
    """
    Return the AppleScript lines that read a titled window's address, if any.

    The app name is one of this module's known browsers, never page
    text.
    """
    name = app_name.lower()
    target: Optional[str] = None
    if name in _TAB_URL_APPS:
        # Chromium family: the address belongs to the window's active tab.
        target = "URL of active tab of (first window whose title is page)"
    elif name == "safari":
        # Safari: the address belongs to the document.
        target = "URL of (first document whose name is page)"
    if target is None:
        return None
    return (
        "on run argv",
        "set page to item 1 of argv",
        f'tell application "{app_name}" to return {target}',
        "end run",
    )


def screen_locked() -> bool:
    """
    Report whether the console session's screen is locked.
    """
    graphics, foundation = _quartz()
    session = graphics.CGSessionCopyCurrentDictionary()
    locked = False
    if session:
        key = foundation.CFStringCreateWithCString(
            None, b"CGSSessionScreenIsLocked", _CF_UTF8
        )
        value = foundation.CFDictionaryGetValue(session, key)
        locked = bool(value) and bool(foundation.CFBooleanGetValue(value))
        foundation.CFRelease(key)
        foundation.CFRelease(session)
    return locked


def seconds_since_person_input() -> float:
    """
    Return the seconds since the last physical mouse or keyboard input.
    """
    graphics, _ = _quartz()
    idle = float(
        graphics.CGEventSourceSecondsSinceLastEventType(
            _HID_SYSTEM_STATE, _ANY_INPUT_EVENT
        )
    )
    return idle


@functools.lru_cache(maxsize=1)
def _quartz() -> Tuple[ctypes.CDLL, ctypes.CDLL]:
    """
    Load CoreGraphics and CoreFoundation with the signatures used here.
    """
    frameworks = "/System/Library/Frameworks"
    graphics = ctypes.cdll.LoadLibrary(
        f"{frameworks}/CoreGraphics.framework/CoreGraphics"
    )
    foundation = ctypes.cdll.LoadLibrary(
        f"{frameworks}/CoreFoundation.framework/CoreFoundation"
    )
    graphics.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    graphics.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
    graphics.CGEventSourceSecondsSinceLastEventType.argtypes = [
        ctypes.c_int32,
        ctypes.c_uint32,
    ]
    foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
    foundation.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    foundation.CFDictionaryGetValue.restype = ctypes.c_void_p
    foundation.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    foundation.CFBooleanGetValue.restype = ctypes.c_bool
    foundation.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
    foundation.CFRelease.argtypes = [ctypes.c_void_p]
    return graphics, foundation


def _healthy(url: str) -> bool:
    """
    Report whether ``url`` responds with a healthy status.
    """
    try:
        response = httpx.get(
            url, timeout=_HEALTH_TIMEOUT_S, follow_redirects=False
        )
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
                time.sleep(_CAPTURE_POLL_S)
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
