"""
MacOS Keychain secret store via the ``security`` command-line tool.

Locators are ``<service>/<account>`` paths, or a bare ``<account>``
under the configured default service. The ``security`` binary is invoked
with an injectable runner so the store is testable without a Keychain.

Import as:

import operant.adapters.secrets.keychain as keychain
"""

from __future__ import annotations

import collections.abc
import dataclasses
import subprocess
from typing import Optional, Tuple

import operant.domain.errors as errors

_SECURITY = "security"
# Keychain "item not found" status (errSecItemNotFound).
_MISSING_STATUS = 44
_TIMEOUT_S = 15.0
# ``security -i`` exits 0 even when a command fails; it reports the
# failing command's status on stderr instead.
_INTERACTIVE_FAILURE = "returned "


# #############################################################################
# CommandResult
# #############################################################################


@dataclasses.dataclass(frozen=True)
class CommandResult:
    """
    Outcome of one ``security`` invocation.

    :ivar returncode: process exit status.
    :ivar stdout: captured standard output.
    :ivar stderr: captured standard error.
    """

    returncode: int
    stdout: str
    stderr: str


Runner = collections.abc.Callable[
    [collections.abc.Sequence[str], Optional[str]], CommandResult
]


def _subprocess_runner(
    argv: collections.abc.Sequence[str], stdin: Optional[str]
) -> CommandResult:
    """
    Run ``security`` as a subprocess and capture its output.
    """
    try:
        completed = subprocess.run(
            list(argv),
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as err:
        raise errors.SecretBackendUnavailableError(
            f"Keychain did not answer within {_TIMEOUT_S:.0f}s"
        ) from err
    result = CommandResult(
        completed.returncode, completed.stdout, completed.stderr
    )
    return result


# #############################################################################
# KeychainSecretStore
# #############################################################################


class KeychainSecretStore:
    """
    Read and writes generic passwords in the login Keychain.

    :ivar backend: always ``"keychain"``.
    """

    backend = "keychain"

    def __init__(
        self, default_service: str = "operant", runner: Optional[Runner] = None
    ) -> None:
        self._service = default_service
        self._run = runner or _subprocess_runner

    def get(self, locator: str) -> Optional[str]:
        """
        Return the stored password, or ``None`` when no item matches.
        """
        service, account = self._split(locator)
        result = self._run(
            [
                _SECURITY,
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            None,
        )
        if result.returncode == 0:
            # Success: the password came back on stdout.
            value = result.stdout.rstrip("\n") or None
        elif result.returncode == _MISSING_STATUS:
            # No such item: report absence, not an error.
            value = None
        else:
            # Any other status is a real backend failure.
            raise errors.SecretBackendUnavailableError(
                f"keychain lookup failed ({result.returncode}): "
                f"{result.stderr.strip()}"
            )
        return value

    def exists(self, locator: str) -> bool:
        """
        Report whether an item exists without reading its value.
        """
        service, account = self._split(locator)
        result = self._run(
            [_SECURITY, "find-generic-password", "-s", service, "-a", account],
            None,
        )
        if result.returncode not in (0, _MISSING_STATUS):
            raise errors.SecretBackendUnavailableError(
                f"keychain lookup failed ({result.returncode}): "
                f"{result.stderr.strip()}"
            )
        present = result.returncode == 0
        return present

    def set(self, locator: str, value: str) -> None:
        """
        Create or update the item (``-U`` upserts).

        The command goes to ``security -i`` on stdin, so the value never
        appears in the process list.
        """
        if "\n" in value or "\r" in value:
            raise errors.SecretBackendUnavailableError(
                "Keychain values cannot contain line breaks"
            )
        service, account = self._split(locator)
        command = (
            f"add-generic-password -U -s {_quoted(service)} "
            f"-a {_quoted(account)} -w {_quoted(value)}\n"
        )
        result = self._run([_SECURITY, "-i"], command)
        if result.returncode != 0 or _INTERACTIVE_FAILURE in result.stderr:
            raise errors.SecretBackendUnavailableError(
                f"keychain write failed ({result.returncode}): "
                f"{result.stderr.strip()}"
            )

    def _split(self, locator: str) -> Tuple[str, str]:
        """
        Split a locator into ``(service, account)``.
        """
        service, sep, account = locator.rpartition("/")
        if not sep:
            # Bare account: fall back to the default service.
            resolved = (self._service, locator)
        else:
            # Explicit "<service>/<account>" locator.
            resolved = (service, account)
        return resolved


def _quoted(text: str) -> str:
    """
    Quote one argument for the ``security -i`` command parser.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    quoted = f'"{escaped}"'
    return quoted
