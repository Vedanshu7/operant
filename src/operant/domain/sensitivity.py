"""
Data classification for the guardrails: what counts as sensitive.

Pure. Signals are unioned (control role, field name or label, the
value's own shape, and the model's declaration) so no single party,
least of all the model, can opt a value out of the human gate. The
strongest class wins.

Typical usage example:

  dc = classify(name="Password", value="hunter2")
  if is_sensitive(dc):
      shown = preview("hunter2", dc)  # "[credential, 7 chars]"

Import as:

import operant.domain.sensitivity as sensv
"""

from __future__ import annotations

import collections.abc
import re
from typing import Dict, Final, List, Optional, Tuple, Union, cast

import operant.domain.models.artifact as artifact

_RANK: Final[Dict[str, int]] = {
    "none": 0,
    "pii": 1,
    "financial": 2,
    "credential": 3,
}

SECURE_ROLES: Final = frozenset({"password_field"})
# Mask glyphs a UI may substitute for masked text. Chrome exposes web
# password inputs as plain text fields whose value reads back as
# bullets, not as an AXSecureTextField, so masking is detected by
# content, not by role.
MASK_CHARS: Final = frozenset("•*·●∗")  # noqa: RUF001 - look-alike glyph

_NAME_PATTERNS: Final[Dict[artifact.DataClass, re.Pattern[str]]] = {
    "credential": re.compile(
        r"password|passwd|passcode|\bpin\b|\botp\b|one.?time.?(code|pass)"
        r"|secret|token|api.?key|\bcvv\b|\bcvc\b|security.?code"
        r"|verification.?code|user.?name|login.?id",
        re.IGNORECASE,
    ),
    "financial": re.compile(
        r"balance|account.?(id|number|no\b|num)|\bacct\b|routing|\biban\b"
        r"|\bswift\b|\bbic\b|card.?(number|no\b|num)|credit.?card"
        r"|debit.?card|salary|wage|income",
        re.IGNORECASE,
    ),
    "pii": re.compile(
        r"\bssn\b|social.?security|date.?of.?birth|\bdob\b|birth.?(date|day)"
        r"|phone|mobile|\btel\b|telephone|e-?mail|address|street|\bzip\b"
        r"|postal|passport|licen[cs]e|national.?id",
        re.IGNORECASE,
    ),
}

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
_PHONE_SHAPE_RE = re.compile(r"^\s*\+?[\d\s().-]+\s*$")
_CARD_SHAPE_RE = re.compile(r"^\s*(?:\d[ -]?){13,19}\s*$")
# Value shapes that are sensitive wherever they appear in free text; the
# PII scrubber registers them so both layers agree on what is sensitive.
VALUE_PATTERNS: Final[Dict[str, re.Pattern[str]]] = {
    "IBAN": _IBAN_RE,
    "SSN": _SSN_RE,
    "EMAIL": _EMAIL_RE,
}


_ASKS_CREDENTIAL_RE: Final = re.compile(
    r"\bcredentials?\b|\blog\s?in\s+details\b", re.IGNORECASE
)


def asks_for_credential(text: str) -> bool:
    """
    Report whether ``text`` asks for a credential (username, password...).

    Used to keep credential questions out of the visible clarify
    channel.

    :param text: a question the agent wants to put to a human.
    :return: whether it names a credential.
    """
    found = bool(
        _NAME_PATTERNS["credential"].search(text)
        or _ASKS_CREDENTIAL_RE.search(text)
    )
    return found


def strongest(
    *classes: Optional[Union[artifact.DataClass, str]],
) -> artifact.DataClass:
    """
    Return the highest-ranked class among the arguments.

    :param *classes: data classes; ``None``, empty, and unknown strings
    rank     as ``none``.
    :return: the strongest class, ``none`` when nothing ranks higher.
    """
    best: artifact.DataClass = "none"
    for dc in classes:
        if dc and _RANK.get(dc, 0) > _RANK[best]:
            best = cast(artifact.DataClass, dc)
    return best


def is_sensitive(dc: Optional[Union[artifact.DataClass, str]]) -> bool:
    """
    Report whether a class is anything other than ``none``.

    :param dc: the data class to test.
    :return: ``True`` for pii, financial, and credential.
    """
    sensitive = bool(dc) and dc != "none"
    return sensitive


def luhn_ok(digits: str) -> bool:
    """
    Check a digit string against the Luhn checksum.

    :param digits: digits only, no separators.
    :return: ``True`` when the checksum holds.
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    valid = total % 10 == 0
    return valid


def _classify_text(
    text: str, extra: collections.abc.Sequence[Tuple[str, artifact.DataClass]]
) -> artifact.DataClass:
    """
    Classify a field name or label by the built-in and extra patterns.
    """
    found: artifact.DataClass = "none"
    for dc, pattern in _NAME_PATTERNS.items():
        if pattern.search(text):
            found = strongest(found, dc)
    for pattern_text, dc in extra:
        if re.search(pattern_text, text, re.IGNORECASE):
            found = strongest(found, dc)
    return found


def _classify_value(value: str) -> artifact.DataClass:
    """
    Classify a value by its own shape.
    """
    dc: artifact.DataClass = "none"
    if _CARD_SHAPE_RE.match(value) and luhn_ok(re.sub(r"\D", "", value)):
        # Card-shaped and Luhn-valid: financial.
        dc = "financial"
    elif _IBAN_RE.search(value):
        # IBAN: financial.
        dc = "financial"
    elif _SSN_RE.search(value):
        # US social security number: pii.
        dc = "pii"
    elif _EMAIL_RE.search(value):
        # Email address: pii.
        dc = "pii"
    else:
        # Otherwise a phone-shaped run of 10-15 digits is pii.
        digit_count = len(re.sub(r"\D", "", value))
        if _PHONE_SHAPE_RE.match(value) and 10 <= digit_count <= 15:
            dc = "pii"
    return dc


def parse_extra_patterns(
    patterns: collections.abc.Sequence[str],
) -> List[Tuple[str, artifact.DataClass]]:
    """
    Parse policy-supplied field patterns.

    ``financial:amount`` pins a class; a bare pattern defaults to pii.

    :param patterns: raw entries from
        ``ApprovalPolicy.sensitive_field_patterns``.
    :return: ``(regex, data class)`` pairs in input order.
    """
    out: List[Tuple[str, artifact.DataClass]] = []
    for raw in patterns:
        prefix, sep, rest = raw.partition(":")
        if sep and prefix in _RANK and prefix != "none":
            out.append((rest, cast(artifact.DataClass, prefix)))
        else:
            out.append((raw, "pii"))
    return out


def classify(
    *,
    name: Optional[str] = None,
    label: Optional[str] = None,
    value: Optional[str] = None,
    control_role: Optional[str] = None,
    control_value: Optional[str] = None,
    declared: Optional[Union[artifact.DataClass, str]] = None,
    extra_patterns: collections.abc.Sequence[str] = (),
) -> artifact.DataClass:
    """
    Union every sensitivity signal and return the strongest class.

    :param name: accessible name of the field.
    :param label: nearby anchoring text of the field.
    :param value: the value about to be typed.
    :param control_role: accessibility role of the field.
    :param control_value: current on-screen value of the field.
    :param declared: class declared by the model or caller.
    :param extra_patterns: policy-supplied field patterns.
    :return: the strongest class any signal produced.
    """
    extra = parse_extra_patterns(extra_patterns)
    found = strongest(declared)
    if control_role in SECURE_ROLES:
        found = strongest(found, "credential")
    if control_value and all(ch in MASK_CHARS for ch in control_value):
        found = strongest(found, "credential")
    for text in (name, label):
        if text:
            found = strongest(found, _classify_text(text, extra))
    if value:
        found = strongest(found, _classify_value(value))
    return found


def preview(value: Optional[str], dc: Union[artifact.DataClass, str]) -> str:
    """
    Describe a value for a prompt or log without revealing it.

    :param value: the sensitive value.
    :param dc: its data class.
    :return: ``[<class>, <n> chars]`` or ``[<class>, empty]``.
    """
    if not value:
        shown = f"[{dc}, empty]"
    else:
        shown = f"[{dc}, {len(value)} chars]"
    return shown
