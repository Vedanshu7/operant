import collections.abc
from typing import Dict, List, Optional, Tuple

import pytest

import operant.adapters.secrets.chained as chained
import operant.adapters.secrets.env as env
import operant.adapters.secrets.factory as factory
import operant.adapters.secrets.keychain as keychain
import operant.domain.errors as errors
import operant.infra.settings as settings
import operant.ports.secrets as secrets


def test_env_store_reads_and_refuses_writes() -> None:
    store = env.EnvSecretStore({"APP_PW": "hunter2", "EMPTY": ""})
    assert isinstance(store, secrets.SecretStore)
    assert store.get("APP_PW") == "hunter2"
    assert store.get("EMPTY") is None and not store.exists("EMPTY")
    with pytest.raises(errors.SecretBackendUnavailableError):
        store.set("APP_PW", "x")


# #############################################################################
# FakeSecurity
# #############################################################################


class FakeSecurity:

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}
        self.calls: List[List[str]] = []

    def __call__(
        self, argv: collections.abc.Sequence[str], stdin: Optional[str]
    ) -> keychain.CommandResult:
        args = list(argv)
        self.calls.append(args)
        service, account = (
            args[args.index("-s") + 1],
            args[args.index("-a") + 1],
        )
        if args[1] == "find-generic-password":
            value = self.items.get((service, account))
            if value is None:
                return keychain.CommandResult(44, "", "item not found")
            return keychain.CommandResult(0, value + "\n", "")
        self.items[(service, account)] = args[args.index("-w") + 1]
        return keychain.CommandResult(0, "", "")


def test_keychain_store_round_trips_through_security_cli() -> None:
    fake = FakeSecurity()
    store = keychain.KeychainSecretStore("operant", runner=fake)
    assert store.get("parabank/password") is None
    store.set("parabank/password", "demo")
    assert store.get("parabank/password") == "demo"
    assert store.exists("password") is False
    store.set("password", "under-default-service")
    assert fake.items[("operant", "password")] == "under-default-service"
    assert all(call[0] == "security" for call in fake.calls)


def test_keychain_store_surfaces_other_failures() -> None:
    def broken(
        argv: collections.abc.Sequence[str], stdin: Optional[str]
    ) -> keychain.CommandResult:
        return keychain.CommandResult(1, "", "keychain locked")

    store = keychain.KeychainSecretStore(runner=broken)
    with pytest.raises(errors.SecretBackendUnavailableError):
        store.get("x")


def test_chained_store_prefers_first_hit_and_first_writable() -> None:
    fake = FakeSecurity()
    first = keychain.KeychainSecretStore("svc", runner=fake)
    second = env.EnvSecretStore({"APP_PW": "from-env"})
    store = chained.ChainedSecretStore([first, second])
    assert store.backend == "keychain+env"
    assert store.get("APP_PW") == "from-env"
    store.set("APP_PW", "from-keychain")
    assert store.get("APP_PW") == "from-keychain"
    read_only = chained.ChainedSecretStore([second])
    with pytest.raises(errors.SecretBackendUnavailableError):
        read_only.set("APP_PW", "x")


def test_factory_picks_backend() -> None:
    assert factory.secret_store(settings.SecretsSettings()).backend == "env"
    chain = factory.secret_store(settings.SecretsSettings(backend="keychain"))
    assert chain.backend == "keychain+env"
