"""
Build the configured secret store.

Import as:

import operant.adapters.secrets.factory as factory
"""

from __future__ import annotations

import operant.adapters.secrets.chained as chained
import operant.adapters.secrets.env as env
import operant.adapters.secrets.keychain as keychain
import operant.infra.settings as settings
import operant.ports.secrets as secrets


def secret_store(
    config: settings.SecretsSettings,
) -> secrets.SecretStore:
    """
    Return the store for ``config.backend``.

    ``keychain`` is chained with ``env`` so demo credentials in ``.env``
    keep working while real ones move to the Keychain.

    :param config: The secrets settings group.
    :return: A ready-to-use store.
    """
    env_store = env.EnvSecretStore()
    store: secrets.SecretStore
    if config.backend == "keychain":
        # Layer the Keychain ahead of env so real secrets win.
        store = chained.ChainedSecretStore(
            [keychain.KeychainSecretStore(config.keychain_service), env_store]
        )
    else:
        # Use env alone when no Keychain backend is configured.
        store = env_store
    return store
