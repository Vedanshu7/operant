from typing import Dict

import pytest

import operant.adapters.secrets.env as env
import operant.application.secrets as secrets
import operant.domain.errors as errors
import operant.domain.models.artifact as artifact
import operant.domain.redaction as redact

TENANT = artifact.TenantBinding(
    base_url="http://x",
    secret_refs={"password": "APP_PW", "username": "keychain:app/user"},
)


def _resolver(
    environ: Dict[str, str], redactor: redact.Redactor
) -> secrets.SecretResolver:
    return secrets.SecretResolver(TENANT, env.EnvSecretStore(environ), redactor)


def test_resolve_registers_value_with_the_redactor() -> None:
    redactor = redact.Redactor()
    resolver = _resolver({"APP_PW": "hunter2-pw"}, redactor)
    assert resolver.resolve("password") == "hunter2-pw"
    assert redactor.redact("typed hunter2-pw") == "typed [REDACTED]"


def test_locator_scheme_is_stripped_before_the_store() -> None:
    redactor = redact.Redactor()
    # keychain:app/user parses to locator "app/user"; the env store won't have
    # it, so this resolves to not-found rather than leaking the scheme.
    resolver = _resolver({"app/user": "john"}, redactor)
    assert resolver.resolve("username") == "john"


def test_missing_secret_names_the_reference_only() -> None:
    resolver = _resolver({}, redact.Redactor())
    with pytest.raises(errors.SecretNotFoundError) as caught:
        resolver.resolve("password")
    assert caught.value.name == "password"
    assert caught.value.available == ["password", "username"]
    assert "APP_PW" not in str(caught.value)


def test_resolve_available_skips_missing() -> None:
    resolver = _resolver({"APP_PW": "pw"}, redact.Redactor())
    assert resolver.resolve_available() == {"password": "pw"}
    assert resolver.names() == ["password", "username"]
    assert resolver.placeholder("password") == "$secret:password"
