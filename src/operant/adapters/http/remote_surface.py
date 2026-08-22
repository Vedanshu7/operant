"""
RemoteGatewaySurface: the client side of the driver protocol.

Implements the same ``Surface`` interface as the in-process gateway, so
the replay engine, discovery loop, drive REPL, and escalation machinery
run unchanged over a driver daemon on any OS. A bearer token
authenticates the loopback (or ``host.docker.internal``) hop to the
daemon.

Import as:

import operant.adapters.http.remote_surface as remote_s
"""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import pathlib
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

import operant.application.gateway.wire as wire
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest

Event = dict[str, Any]

_APPROVAL_REQUIRED = 428
_POLICY_DENIED = 403
_ALL_TOOLS_FAILED = 502


def _no_event(_event: Event) -> None:
    """
    Drop the event (default sink).
    """


# #############################################################################
# RemoteGatewaySurface
# #############################################################################


class RemoteGatewaySurface:
    """
    Speak the driver HTTP protocol as a local ``Surface``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: Optional[str] = None,
        on_event: collections.abc.Callable[[Event], None] = _no_event,
        client: Optional[httpx.Client] = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client or httpx.Client(
            base_url=base_url, timeout=120.0, headers=headers
        )
        self._on_event = on_event
        self._last_digest: Optional[digest.ScreenDigest] = None
        self._poll_stop: Optional[threading.Event] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._check_protocol(base_url)

    def health_table(self) -> List[Dict[str, Any]]:
        """
        Return the daemon's per-tool health rows.
        """
        response = self._client.get("/health")
        response.raise_for_status()
        tools: List[Dict[str, Any]] = response.json().get("tools", [])
        return tools

    def snapshot(self) -> digest.ScreenDigest:
        """
        Observe the bound window through the daemon.
        """
        response = self._client.post("/observe")
        response.raise_for_status()
        self._last_digest = wire.digest_from_dict(response.json()["digest"])
        return self._last_digest

    def retarget(
        self, app_name: str, window_title_pattern: str
    ) -> Tuple[str, str]:
        """
        Rebind the daemon's session to another window.
        """
        response = self._client.post(
            "/retarget",
            json={
                "app_name": app_name,
                "window_title_pattern": window_title_pattern,
            },
        )
        response.raise_for_status()
        previous = response.json().get("previous", ["", ""])
        result = (previous[0], previous[1])
        return result

    def grant_scope(self, grant: daapprov.ScopeGrant) -> None:
        """
        Send a human-approved scope grant to the daemon.
        """
        self._client.post(
            "/policy/grant", json=grant.model_dump(mode="json")
        ).raise_for_status()

    def target_text_for(self, ref: Optional[str]) -> str:
        """
        Return the human-readable text of a control from the last digest.
        """
        text = ""
        if ref is not None and self._last_digest is not None:
            for control in self._last_digest.controls:
                if control.ref == ref:
                    text = " | ".join(
                        x for x in (control.name, control.label) if x
                    )
                    break
        return text

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run one action, mapping the daemon's status codes to exceptions.
        """
        if action.ref is not None and not action.target_text:
            action = dataclasses.replace(
                action, target_text=self.target_text_for(action.ref)
            )
        response = self._client.post(
            "/perform",
            json={"action": wire.action_to_dict(action), "approval": approval},
        )
        self._raise_for_perform(response, action)
        result = self._journal_success(response.json(), action)
        return result

    def screenshot(self, path: pathlib.Path) -> bool:
        """
        Save the daemon's screenshot to ``path``.
        """
        try:
            response = self._client.get("/screenshot")
        except httpx.HTTPError as err:
            raise errors.SurfaceError(
                f"driver /screenshot failed: {err}"
            ) from err
        if response.status_code != 200:
            raise errors.SurfaceError(
                f"driver /screenshot HTTP {response.status_code}"
                + self._error_detail(response)
            )
        path.write_bytes(response.content)
        return True

    def start_human_capture(
        self, on_action: collections.abc.Callable[[str], None]
    ) -> None:
        """
        Poll the daemon's human-action buffer during a hand-off.
        """
        self._client.post("/capture/start")
        stop = threading.Event()
        self._poll_stop = stop
        self._poll_thread = threading.Thread(
            target=self._poll_actions, args=(stop, on_action), daemon=True
        )
        self._poll_thread.start()

    def stop_human_capture(self) -> None:
        """
        Stop the human-action poller.
        """
        if self._poll_stop is not None:
            self._poll_stop.set()
        self._poll_thread = None
        self._poll_stop = None
        with contextlib.suppress(httpx.HTTPError):
            self._client.post("/capture/stop")

    def inject_session_expiry(self) -> None:
        """
        Ask the daemon to inject a session-expiry fault.
        """
        self._client.post("/inject-fault", timeout=240.0).raise_for_status()

    def start_capture(
        self,
        out_dir: pathlib.Path,
        task: str,
        window: Optional[Dict[str, Optional[str]]],
        *,
        video: bool = True,
    ) -> bool:
        """
        Start full UI capture on the daemon; ``False`` when unavailable.
        """
        try:
            response = self._client.post(
                "/capture/session/start",
                json={
                    "out_dir": str(out_dir),
                    "task": task,
                    "window": window,
                    "video": video,
                },
            )
            started = response.status_code == 200
        except httpx.HTTPError:
            started = False
        return started

    def stop_capture(self) -> Dict[str, Any]:
        """
        Stop full UI capture and returns the daemon's summary.
        """
        try:
            response = self._client.post("/capture/session/stop", timeout=120.0)
            summary = response.json() if response.status_code == 200 else {}
        except httpx.HTTPError:
            summary = {}
        return summary

    def close(self) -> None:
        """
        Stop capture; the daemon persists (its grant outlives us).
        """
        self.stop_human_capture()

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """
        Return the daemon's error string as a suffix, or ``""``.
        """
        try:
            detail = response.json().get("error", "")
        except ValueError:
            detail = ""
        formatted = f": {detail}" if detail else ""
        return formatted

    def _check_protocol(self, base_url: str) -> None:
        """
        Verify the daemon speaks this client's protocol version.
        """
        try:
            response = self._client.get("/health")
            response.raise_for_status()
            spoken = str(response.json().get("protocol", ""))
        except (httpx.HTTPError, ValueError) as err:
            raise errors.DriverError(
                f"driver daemon at {base_url} is not reachable: {err}"
            ) from err
        if spoken != wire.PROTOCOL_VERSION:
            raise errors.DriverError(
                f"driver daemon speaks protocol {spoken!r}, this client needs "
                f"{wire.PROTOCOL_VERSION!r} - restart `operant serve-driver` "
                "from the current checkout"
            )

    def _raise_for_perform(
        self, response: httpx.Response, action: actions.SurfaceAction
    ) -> None:
        """
        Raise the mapped error for a non-OK ``/perform`` response.
        """
        if response.status_code == _APPROVAL_REQUIRED:
            body = response.json()
            raise errors.ApprovalRequiredError(
                wire.approval_request_from_dict(body["request"]),
                body["nonce"],
                action,
            )
        if response.status_code == _POLICY_DENIED:
            decision = response.json()["decision"]
            raise errors.PolicyViolationError(
                daapprov.PolicyDecision(
                    verdict=decision.get("verdict", "deny"),
                    risk=decision["risk"],
                    reason=decision["reason"],
                )
            )
        if response.status_code == _ALL_TOOLS_FAILED:
            self._raise_all_failed(response, action)
        if response.status_code >= 400:
            raise errors.DriverError(
                f"driver /perform HTTP {response.status_code}"
                + self._error_detail(response)
            )

    def _raise_all_failed(
        self, response: httpx.Response, action: actions.SurfaceAction
    ) -> None:
        """
        Raise a ``DriverError`` after journaling each failed attempt.
        """
        attempts = response.json().get("attempts", [])
        for attempt in attempts:
            self._on_event(
                {"type": "gateway_action", "action": action.kind, **attempt}
            )
        detail = "; ".join(
            f"{a['tool']}: {a['status']} ({a.get('reason', '')})"
            for a in attempts
        )
        raise errors.DriverError(
            f'every tool for "{action.kind}" failed - {detail}'
        )

    def _journal_success(
        self, body: Dict[str, Any], action: actions.SurfaceAction
    ) -> Dict[str, Any]:
        """
        Emit gateway events for each attempt and return the body.
        """
        for attempt in body.get("attempts", []):
            self._on_event(
                {"type": "gateway_action", "action": action.kind, **attempt}
            )
        if not body.get("attempts"):
            self._on_event(
                {
                    "type": "gateway_action",
                    "action": action.kind,
                    "tool": body.get("tool"),
                    "status": "ok",
                }
            )
        return body

    def _poll_actions(
        self,
        stop: threading.Event,
        on_action: collections.abc.Callable[[str], None],
    ) -> None:
        """
        Poll the daemon's action buffer until ``stop`` is set.
        """
        seen = 0
        while not stop.is_set():
            try:
                entries = (
                    self._client.get("/capture/actions").json().get("actions", [])
                )
                for entry in entries[seen:]:
                    on_action(entry)
                seen = len(entries)
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
