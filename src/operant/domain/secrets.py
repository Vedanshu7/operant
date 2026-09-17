"""
The secret-reference grammar: names the model sees, locators it never does.

A tenant binds reference names to locators such as ``env:PARABANK_PASSWORD``
or ``keychain:operant/parabank/password``. A bare locator with no scheme is an
environment variable name, which keeps every pre-existing profile valid.

Import as:

import operant.domain.secrets as odsec
"""

import dataclasses
import re
from typing import Final, FrozenSet, List, Literal, Optional

import operant.domain.errors as errors

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
        :raises errors.ConfigError: if the locator is empty
        """
        backend, sep, rest = text.partition(":")
        if not sep or backend not in _KNOWN_BACKENDS:
            backend, rest = "env", text
        if not rest.strip():
            raise errors.ConfigError(f"Empty secret locator in '{text}'")
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


# Words that tell what a credential is, by kind. A secret's name and the
# field it goes into must share a kind: a password never goes into a
# field that is not asking for one.
_KINDS: Final = (
    ("pass", "pwd", "pw", "pin", "secret"),
    ("user", "login", "email"),
    ("otp", "code", "token", "mfa", "2fa", "verification"),
)
_WORD_RE: Final = re.compile(r"[a-z0-9]+")


def _words(text: str) -> List[str]:
    """
    Lower-case words of a name or label, splitting camelCase and snake_case.
    """
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return _WORD_RE.findall(spaced.lower())


def fits_field(secret_name: str, field_text: str) -> bool:
    """
    Report whether a credential may be typed into a field.

    The secret's kinds come from its name: a kind word anywhere in it
    counts (``logincode`` is a login and a code, ``pw_ref`` a password).
    The field must have a word starting with a word of the same kind, so
    "Password" fits ``pw_ref`` but "Shipping" never fits ``pin``. A
    secret of no known kind (``api_key``) needs one of its own words in
    the field. This keeps a page from collecting a password through a
    field it labels something else.

    :param secret_name: the secret reference name.
    :param field_text: the target control's name and label.
    :return: ``True`` when the field asks for this kind of credential.
    """
    secret = "".join(_words(secret_name))
    field = _words(field_text)
    kinds = [words for words in _KINDS if any(w in secret for w in words)]
    if kinds:
        fits = any(
            word.startswith(keyword)
            for words in kinds
            for keyword in words
            for word in field
        )
    else:
        fits = bool(set(_words(secret_name)) & set(field))
    return fits
