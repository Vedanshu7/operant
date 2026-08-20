"""
Turning a tenant's secret reference names into values, redacting as we go.

Every place that resolves a reference - replay, discovery, the drive
REPL - goes through ``SecretResolver``, the single point that (a) parses
the locator, (b) asks the ``SecretStore`` backend, and (c) registers the
value with the redactor before it can reach a log. Swapping env vars for
a vault means a new ``SecretStore``; nothing upstream changes.

Import as:

import operant.application.secrets as secrets
"""

from __future__ import annotations

from typing import Dict, List

import operant.domain.errors as errors
import operant.domain.models.artifact as artifact
import operant.domain.redaction as redact
import operant.domain.secrets as secrets
import operant.ports.secrets as pssecret

# #############################################################################
# SecretResolver
# #############################################################################


class SecretResolver:
    """
    Resolve one tenant's secret references through a store.
    """

    def __init__(
        self,
        tenant: artifact.TenantBinding,
        store: pssecret.SecretStore,
        redactor: redact.Redactor,
    ) -> None:
        self._refs = dict(tenant.secret_refs)
        self._transient: Dict[str, str] = {}
        self._store = store
        self._redactor = redactor

    def names(self) -> List[str]:
        """
        Return every available reference name, sorted.
        """
        available = sorted(set(self._refs) | set(self._transient))
        return available

    def placeholder(self, name: str) -> str:
        """
        Return the ``$secret:<name>`` token the model may type.
        """
        token = secrets.placeholder(name)
        return token

    def add_transient(self, name: str, value: str) -> None:
        """
        Hold a human-typed credential for this run only, redacted.

        Never persisted: the capability records the reference name, so an
        unattended replay needs the value supplied again (or a locator).
        """
        self._transient[name] = value
        self._redactor.add_secret(value)

    def add_reference(self, name: str, locator: str) -> None:
        """
        Bind ``name`` to a locator (``env:X`` / ``keychain:svc/acct``).

        :raises ValueError: If the locator is malformed.
        """
        secrets.SecretRef.parse(locator)
        self._refs[name] = locator

    def resolve(self, name: str) -> str:
        """
        Resolve one reference and registers the value with the redactor.

        A run-held transient value wins over a stored locator.

        :param name: The reference name.
        :return: The secret value.
        """
        value = self._transient.get(name)
        if value is None:
            locator = self._refs.get(name)
            if locator is not None:
                value = self._store.get(secrets.SecretRef.parse(locator).locator)
        if value is None:
            raise errors.SecretNotFoundError(name, self.names())
        self._redactor.add_secret(value)
        return value

    def resolve_available(self) -> Dict[str, str]:
        """
        Resolve every reference the store can satisfy; skips the rest.
        """
        resolved: Dict[str, str] = {}
        for name in self._refs:
            try:
                resolved[name] = self.resolve(name)
            except errors.SecretNotFoundError:
                continue
        return resolved
