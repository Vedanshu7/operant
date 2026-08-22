"""
Launching the target in a dedicated, automation-owned instance.

Import as:

import operant.adapters.macos.tools.launcher as launcher
"""

from __future__ import annotations

import json
import os
import pathlib
import plistlib
import shutil
import signal
import subprocess
import time
import unicodedata
from typing import List, Optional

import operant.adapters.macos.session as mssessio
import operant.domain.models.actions as actions
import operant.domain.models.tools as tools
import operant.infra.settings as settings

_CHROME_FLAGS = (
    "--force-renderer-accessibility",
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-crash-restore-bubble",
    # Suppress Chrome's own dialogs so discovery records only the real
    # task, not clicks that dismiss a keychain/password/leak prompt.
    "--use-mock-keychain",
    "--password-store=basic",
    "--disable-save-password-bubble",
    "--disable-search-engine-choice-screen",
    "--disable-features=PasswordLeakDetection,"
    "PasswordManagerOnboarding,AutofillServerCommunication",
)

_BROWSER_TOKENS = frozenset(
    {"chrome", "chromium", "safari", "firefox", "arc", "edge", "brave", "browser"}
)


# #############################################################################
# AppLauncher
# #############################################################################


class AppLauncher:
    """
    Launch the target, isolating browsers into a dedicated profile.

    For Chromium browsers this means a separate ``--user-data-dir`` plus
    ``--force-renderer-accessibility``: the user's personal Chrome
    exposes web form controls to the accessibility tree only
    intermittently, whereas a dedicated instance started with the flag
    exposes them reliably. It is still a real browser with a real
    session - just isolated from the user's browsing, which also removes
    all window/tab contention.
    """

    spec = tools.ToolSpec(
        name="app-launcher", version="1", serves=frozenset({"launch"})
    )

    def __init__(
        self,
        session: mssessio.WindowSession,
        browser: settings.BrowserSettings,
        profile_dir: pathlib.Path,
    ) -> None:
        self.session = session
        self._browser = browser
        self._profile_dir = profile_dir

    @staticmethod
    def reset_dedicated_chrome(profile_dir: pathlib.Path) -> bool:
        """
        Quit the automation browser and wipes its profile.

        The next launch then starts logged out. Never touches the user's
        own browser - PID selection is by our ``--user-data-dir``.

        :param profile_dir: The dedicated profile directory.
        :return: Whether a live instance was found and stopped.
        """
        profile = profile_dir.expanduser()
        marker = f"--user-data-dir={profile}"
        pid = _dedicated_pid(marker)
        if pid is not None:
            _terminate(pid, marker)
        shutil.rmtree(profile, ignore_errors=True)
        was_live = pid is not None
        return was_live

    def health(self) -> tools.ToolHealth:
        """
        Report always-available health; a bad binary path fails at execute
        time.
        """
        report = tools.ToolHealth("ok")
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Open ``action.app``/``action.url``, dedicated for browsers.
        """
        app_name = action.app or self.session.app_name
        if self._is_browser(app_name):
            # Browsers get a dedicated, isolated instance.
            result = self._launch_browser(app_name, action.url)
        else:
            # Native apps open directly.
            result = self._launch_native(app_name, action.url)
        return result

    def _is_browser(self, app_name: str) -> bool:
        """
        Report whether ``app_name`` names a browser, aliases included.

        The configured set holds full product names ("google chrome"),
        but the model often guesses short/other names ("chrome",
        "firefox"). Any recognised browser token routes to the browser
        path, which falls back to the default browser when the exact
        binary is not configured - so a guess never wastes a turn.
        """
        lname = app_name.lower()
        if lname in self._browser.browser_app_names:
            # An exact configured browser name.
            is_browser = True
        else:
            # Otherwise match any known browser token.
            is_browser = any(token in lname for token in _BROWSER_TOKENS)
        return is_browser

    def _launch_native(
        self, app_name: str, url: Optional[str]
    ) -> tools.ToolResult:
        """
        Open a native app and wait for its window.
        """
        try:
            self._open_native(app_name, url)
            self.session.window(timeout=20.0)
            time.sleep(1.5)
            result = tools.ToolResult(status="ok", verified=True)
        except (subprocess.SubprocessError, TimeoutError) as err:
            result = tools.ToolResult(status="failed", reason=str(err))
        return result

    def _open_native(self, app_name: str, url: Optional[str]) -> None:
        """
        Open a native app, resolving the bundle path when the name lookup fails
        (e.g. WhatsApp ships as ``‎WhatsApp.app`` with a leading left-to-right
        mark, so ``open -a WhatsApp`` cannot find it).

        :raises subprocess.SubprocessError: If the app cannot be
            launched.
        """
        try:
            subprocess.run(_open_command(app_name, url), check=True, timeout=20)
        except subprocess.CalledProcessError as miss:
            path = _resolve_app_path(app_name)
            if path is None:
                raise subprocess.SubprocessError(
                    f"application {app_name!r} not found"
                ) from miss
            subprocess.run(_open_command(str(path), url), check=True, timeout=20)

    def _launch_browser(
        self, app_name: str, url: Optional[str]
    ) -> tools.ToolResult:
        """
        Launch or reuse the dedicated browser instance.
        """
        # Fall back to the default browser when the requested one has no
        # configured binary (e.g. the model guessed "Firefox"/"Safari"),
        # so a browser launch always lands in the automation's dedicated
        # instance instead of failing and burning a turn.
        result = None
        binary = self._binary_for(app_name) or self._binary_for(
            self._browser.default_app
        )
        if binary is None:
            # No usable browser binary.
            result = tools.ToolResult(
                status="failed",
                reason=f"browser binary not found for {app_name!r}",
            )
        else:
            # Reuse a live dedicated instance, or start a fresh one.
            marker = f"--user-data-dir={self._profile()}"
            pid = _dedicated_pid(marker)
            if pid is None:
                # No live instance: start one.
                pid = self._start_fresh(binary, marker, url)
                if pid is None:
                    result = tools.ToolResult(
                        status="failed",
                        reason="dedicated browser did not start",
                    )
            elif url:
                # Live instance: open the URL in a new window.
                subprocess.run(
                    [binary, marker, "--new-window", url],
                    check=False,
                    timeout=20,
                )
            if result is None:
                if pid is not None:
                    self.session.bind_pid(pid)
                    self._await_window(binary, marker, url)
                    time.sleep(1.5)
                result = tools.ToolResult(status="ok", verified=True)
        return result

    def _start_fresh(
        self, binary: str, marker: str, url: Optional[str]
    ) -> Optional[int]:
        """
        Start a fresh dedicated browser and return its pid.
        """
        _seed_profile_prefs(self._profile())
        subprocess.Popen(
            [
                binary,
                marker,
                *_CHROME_FLAGS,
                "--new-window",
                *([url] if url else []),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        pid = None
        while pid is None and time.monotonic() < deadline:
            pid = _dedicated_pid(marker)
            if pid is None:
                time.sleep(0.5)
        return pid

    def _await_window(self, binary: str, marker: str, url: Optional[str]) -> None:
        """
        Wait for the window, nudging a new one if none appears.
        """
        try:
            self.session.window(timeout=20.0)
        except TimeoutError:
            # A brand-new profile can miss the very first --new-window; nudge.
            subprocess.run(
                [binary, marker, "--new-window", url or "about:blank"],
                check=False,
                timeout=20,
            )
            self.session.window(timeout=20.0)

    def _binary_for(self, app_name: str) -> Optional[str]:
        """
        Return the configured binary path matching ``app_name``.
        """
        found = None
        for candidate in self._browser.binaries:
            path = pathlib.Path(candidate).expanduser()
            if app_name.lower() in path.name.lower() and path.exists():
                found = str(path)
                break
        return found

    def _profile(self) -> pathlib.Path:
        """
        Return the dedicated profile directory, creating it.
        """
        profile = self._profile_dir.expanduser()
        profile.mkdir(parents=True, exist_ok=True)
        return profile


_APP_DIRS = (
    pathlib.Path("/Applications"),
    pathlib.Path.home() / "Applications",
    pathlib.Path("/System/Applications"),
    pathlib.Path("/System/Applications/Utilities"),
)


def _seed_profile_prefs(profile_dir: pathlib.Path) -> None:
    """
    Turn Chrome's password manager off in a fresh dedicated profile.

    Belt-and-suspenders alongside the launch flags: if a flag stops
    working across Chrome versions, the seeded Preferences still keep the
    save-password and leak-detection dialogs from popping during
    discovery. Only writes when no profile exists yet, so it never
    clobbers a live session's settings.
    """
    default = profile_dir / "Default"
    prefs = default / "Preferences"
    if not prefs.exists():
        default.mkdir(parents=True, exist_ok=True)
        prefs.write_text(
            json.dumps(
                {
                    "credentials_enable_service": False,
                    "profile": {
                        "password_manager_enabled": False,
                        "password_manager_leak_detection": False,
                    },
                }
            ),
            encoding="utf-8",
        )


def _visible(text: str) -> str:
    """
    Strip control/format characters (e.g. the U+200E in some bundles).
    """
    visible = "".join(
        ch for ch in text if not unicodedata.category(ch).startswith("C")
    ).strip()
    return visible


def _bundle_name(app: pathlib.Path) -> str:
    """
    Return the app bundle's ``CFBundleName``, or ``""``.
    """
    try:
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        name = ""
    else:
        name = str(plist.get("CFBundleName") or "")
    return name


def _resolve_app_path(app_name: str) -> Optional[pathlib.Path]:
    """
    Find an installed ``.app`` by display name when ``open -a`` cannot.

    Matches the bundle's visible file name or its ``CFBundleName``,
    case-insensitively, across the standard application directories.
    """
    target = app_name.strip().lower()
    found = None
    for directory in _APP_DIRS:
        if directory.is_dir():
            for app in directory.glob("*.app"):
                if _visible(app.stem).lower() == target:
                    found = app
                    break
                if _bundle_name(app).lower() == target:
                    found = app
                    break
            if found is not None:
                break
    return found


def _open_command(app_name: str, url: Optional[str]) -> List[str]:
    """
    Build the ``open`` argv for an app or URL.
    """
    if url and ("://" in url or url.startswith("x-apple")):
        # A URL scheme (e.g. x-apple.systempreferences:) - let the OS route
        # it to the owning native app.
        command = ["open", url]
    elif url:
        # A plain URL: open it in the app's new window.
        command = ["open", "-na", app_name, "--args", "--new-window", url]
    else:
        # No URL: just open the app.
        command = ["open", "-a", app_name]
    return command


def _terminate(pid: int, marker: str) -> None:
    """
    Terminate the pid, escalating to SIGKILL if it lingers.
    """
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while _dedicated_pid(marker) is not None and time.monotonic() < deadline:
        time.sleep(0.3)
    if _dedicated_pid(marker) is not None:
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)


def _dedicated_pid(marker: str) -> Optional[int]:
    """
    PID of the MAIN browser process for our user-data-dir.

    The main process is the one without a ``--type=`` child-process
    flag.
    """
    # Match on the PATH only: a pattern starting with "--" is parsed by
    # pgrep as flags, so pass the bare path after ``--``.
    path = marker.split("=", 1)[1]
    listed = subprocess.run(
        ["pgrep", "-f", "--", path],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    found = None
    for line in listed.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        args = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        if marker in args and "--type=" not in args:
            found = pid
            break
    return found
