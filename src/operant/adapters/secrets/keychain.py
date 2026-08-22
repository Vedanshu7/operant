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


# #############################################################################
# CommandResult
# #############################################################################


@dataclasses.dataclass(frozen=True)
class CommandResult:
    """
    Outcome of one ``security`` invocation.

    :ivar returncode: Process exit status.
    :ivar stdout: Captured standard output.
    :ivar stderr: Captured standard error.
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
    completed = subprocess.run(
        list(argv),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
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

    :ivar backend: Always ``"keychain"``.
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
        Report whether an item exists without returning its value.
        """
        present = self.get(locator) is not None
        return present

    def set(self, locator: str, value: str) -> None:
        """
        Create or updates the item (``-U`` upserts).
        """
        service, account = self._split(locator)
        result = self._run(
            [
                _SECURITY,
                "add-generic-password",
                "-U",
                "-s",
                service,
                "-a",
                account,
                "-w",
                value,
            ],
            None,
        )
        if result.returncode != 0:
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
