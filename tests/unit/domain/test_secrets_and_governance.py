import pytest

import operant.domain.governance as govern
import operant.domain.secrets as secrets


@pytest.mark.parametrize(
    ("text", "backend", "locator"),
    [
        ("PARABANK_PASSWORD", "env", "PARABANK_PASSWORD"),
        ("env:PARABANK_PASSWORD", "env", "PARABANK_PASSWORD"),
        (
            "keychain:operant/parabank/password",
            "keychain",
            "operant/parabank/password",
        ),
        ("keychain:password", "keychain", "password"),
    ],
)
def test_secret_ref_parse(text: str, backend: str, locator: str) -> None:
    ref = secrets.SecretRef.parse(text)
    assert (ref.backend, ref.locator) == (backend, locator)
    assert str(ref) == f"{backend}:{locator}"


def test_secret_ref_rejects_empty_locator() -> None:
    with pytest.raises(ValueError):
        secrets.SecretRef.parse("keychain:")


def test_placeholder_round_trip() -> None:
    token = secrets.placeholder("password")
    assert token == "$secret:password"
    assert secrets.placeholder_name(token) == "password"
    assert secrets.placeholder_name("literal") is None


def test_stability_gate() -> None:
    gate = govern.StabilityGate(min_runs=3, min_success_rate=0.8)
    assert not gate.passes(2, 2)
    assert not gate.passes(10, 7)
    assert gate.passes(5, 4)
    assert "4/5 passes" in gate.describe(5, 4)
    assert "0/0 fails" in gate.describe(0, 0)
