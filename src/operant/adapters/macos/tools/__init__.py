"""
The macOS tool set: one small, honest, replaceable tool per mechanism.

Integrating a future driver (CDP, OCR, Windows UIA) is one more class
here plus a chain entry in the gateway policy. Grouped by mechanism:
``observe`` (accessibility digest), ``launcher`` (dedicated app
instances), ``ax`` (pure accessibility actions), ``applescript`` (System
Events keystrokes), and ``os_input`` (synthesized input and coordinate
clicks).

Import as:

import operant.adapters.macos.tools as tools
"""

import operant.adapters.macos.tools.applescript as applescr
import operant.adapters.macos.tools.ax as ax
import operant.adapters.macos.tools.launcher as launcher
import operant.adapters.macos.tools.observe as observe
import operant.adapters.macos.tools.os_input as os_input

AppLauncher = launcher.AppLauncher
Xa11yDigestObserver = observe.Xa11yDigestObserver
AxActionTool = ax.AxActionTool
AxSelectTool = ax.AxSelectTool
AxScrollTool = ax.AxScrollTool
AppleScriptKeysTool = applescr.AppleScriptKeysTool
ClipboardPasteTool = applescr.ClipboardPasteTool
SeSelectTool = applescr.SeSelectTool
SystemEventsPressTool = applescr.SystemEventsPressTool
OsInputTool = os_input.OsInputTool
OsInputScrollTool = os_input.OsInputScrollTool
CoordinateClickTool = os_input.CoordinateClickTool

__all__ = [
    "AppLauncher",
    "AppleScriptKeysTool",
    "AxActionTool",
    "AxScrollTool",
    "AxSelectTool",
    "ClipboardPasteTool",
    "CoordinateClickTool",
    "OsInputScrollTool",
    "OsInputTool",
    "SeSelectTool",
    "SystemEventsPressTool",
    "Xa11yDigestObserver",
]
