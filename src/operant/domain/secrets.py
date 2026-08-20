"""
The secret-reference grammar: names the model sees, locators it never does.

A tenant binds reference names to locators such as ``env:PARABANK_PASSWORD``
or ``keychain:operant/parabank/password``. A bare locator with no scheme is an
environment variable name, which keeps every pre-existing profile valid.

Import as:

import operant.domain.secrets as odsec
"""

import dataclasses
from typing import Final, FrozenSet, Literal, Optional

SecretBackend = Literal["env", "keychain"]

PLACEHOLDER_PREFIX: Final = "$secret:"
_KNOWN_BACKENDS: Final[FrozenSet[str]] = frozenset({"env", "keychain"})


# #############################################################################
# SecretRef
# #############################################################################


@dataclasses.dataclass(frozen=True)
class SecretRef:
    """
    A parsed locator: which store resolves it, and its backend address.
    """

    # Which store resolves the locator.
    backend: SecretBackend
    # Backend-specific address (env var name, or keychain path).
    locator: str

    def __str__(self) -> str:
        """
        Render the canonical ``backend:locator`` form.
        """
        canonical = f"{self.backend}:{self.locator}"
        return canonical

    @classmethod
    def parse(cls, text: str) -> "SecretRef":
        """
        Parse ``"<backend>:<locator>"``; a bare name means ``env``.

        :param text: the locator string from a tenant binding
        :return: the parsed reference
        :raises ValueError: if the backend is unknown or the locator is
            empty
        """
        backend, sep, rest = text.partition(":")
        if not sep or backend not in _KNOWN_BACKENDS:
            backend, rest = "env", text
        if not rest.strip():
            raise ValueError(f"empty secret locator in {text!r}")
        if backend == "keychain":
            ref = cls("keychain", rest)
        else:
            ref = cls("env", rest)
        return ref


# #############################################################################
# CredentialGrant
# #############################################################################


@dataclasses.dataclass(frozen=True)
class CredentialGrant:
    """
    A human's answer to a credential request.

    Exactly one of ``value`` or ``locator`` is set: ``value`` is a
    literal the human typed (held only for the run), ``locator`` names an
    env var or Keychain entry the runtime resolves. Neither ever reaches
    the model - it only gets the ``$secret:<name>`` handle.
    """

    value: Optional[str] = None
    locator: Optional[str] = None

    @classmethod
    def typed(cls, value: str) -> "CredentialGrant":
        """
        Build a grant from a literal credential the human entered.
        """
        grant = cls(value=value)
        return grant

    @classmethod
    def sourced(cls, locator: str) -> "CredentialGrant":
        """
        Build a grant from a locator (``env:X`` / ``keychain:svc/acct``).
        """
        grant = cls(locator=locator)
        return grant


def placeholder(name: str) -> str:
    """
    Return the token the model types to request a secret by name.
    """
    token = f"{PLACEHOLDER_PREFIX}{name}"
    return token


def placeholder_name(text: str) -> Optional[str]:
    """
    Extract the reference name from a placeholder, else ``None``.
    """
    if text.startswith(PLACEHOLDER_PREFIX):
        name = text.removeprefix(PLACEHOLDER_PREFIX)
    else:
        name = None
    return name
