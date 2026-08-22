from __future__ import annotations

import pytest

import operant.domain.sensitivity as sensv


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Password", "credential"),
        ("passcode", "credential"),
        ("PIN", "credential"),
        ("One-time code", "credential"),
        ("API Key", "credential"),
        ("Username", "credential"),
        ("Balance", "financial"),
        ("accountId", "financial"),
        ("Account Number", "financial"),
        ("IBAN", "financial"),
        ("Card number", "financial"),
        ("SSN", "pii"),
        ("Date of birth", "pii"),
        ("Phone", "pii"),
        ("E-mail", "pii"),
        ("Street address", "pii"),
        ("Note title", "none"),
        ("Search", "none"),
        ("Amount", "none"),
    ],
)
def test_name_patterns(name: str, expected: str) -> None:
    assert sensv.classify(name=name) == expected


def test_label_counts_like_name() -> None:
    assert sensv.classify(name="", label="Password") == "credential"


def test_secure_role_and_masked_value_are_credentials() -> None:
    assert sensv.classify(control_role="password_field") == "credential"
    assert (
        sensv.classify(control_role="text_field", control_value="••••••")
        == "credential"
    )
    assert (
        sensv.classify(control_role="text_field", control_value="hello") == "none"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4111 1111 1111 1111", "financial"),
        ("4111-1111-1111-1112", "none"),
        ("GB82WEST12345698765432", "financial"),
        ("123-45-6789", "pii"),
        ("someone@example.com", "pii"),
        ("+1 415 555 0100", "pii"),
        ("(415) 555-0100", "pii"),
        ("2026-08-19", "none"),
        ("13344", "none"),
        ("$10.45", "none"),
        ("Standup\nblocked on X", "none"),
        ("OK", "none"),
    ],
)
def test_value_patterns(value: str, expected: str) -> None:
    assert sensv.classify(value=value) == expected


def test_luhn() -> None:
    assert sensv.luhn_ok("4111111111111111")
    assert not sensv.luhn_ok("4111111111111112")


def test_union_takes_strongest() -> None:
    assert sensv.classify(name="accountId", value="13344") == "financial"
    assert sensv.classify(name="Balance", declared="pii") == "financial"
    assert sensv.classify(name="note", declared="credential") == "credential"
    assert sensv.strongest("pii", None, "financial", "none") == "financial"
    assert sensv.strongest() == "none"


def test_notes_body_shape_is_not_sensitive() -> None:
    assert (
        sensv.classify(
            name="",
            label="August 19, 2026 at 4:00 PM",
            control_role="text_area",
            value="Standup\nblocked on X",
        )
        == "none"
    )


def test_extra_patterns_from_policy() -> None:
    assert sensv.parse_extra_patterns(["financial:amount", "nickname"]) == [
        ("amount", "financial"),
        ("nickname", "pii"),
    ]
    assert (
        sensv.classify(name="Amount", extra_patterns=["financial:amount"])
        == "financial"
    )
    assert sensv.classify(name="Nickname", extra_patterns=["nickname"]) == "pii"


def test_preview_never_contains_the_value() -> None:
    assert "hunter2" not in sensv.preview("hunter2", "credential")
    assert sensv.preview("hunter2", "credential") == ("[credential, 7 chars]")
    assert sensv.preview("", "pii") == "[pii, empty]"


def test_is_sensitive() -> None:
    assert not sensv.is_sensitive("none")
    assert not sensv.is_sensitive(None)
    assert sensv.is_sensitive("pii")
