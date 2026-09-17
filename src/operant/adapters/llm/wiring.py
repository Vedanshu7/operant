"""
Build the model wiring a discovery run uses from settings.

Import as:

import operant.adapters.llm.wiring as alwiring
"""

from __future__ import annotations

import operant.adapters.llm.litellm_client as litecli
import operant.adapters.observability.factory as aofactor
import operant.adapters.privacy.factory as apfactor
import operant.application.usecases.discover as discover
import operant.infra.settings as issettin


def model_wiring(settings: issettin.OperantSettings) -> discover.ModelWiring:
    """
    Build every role's client, the token counter, tracer and scrubber.

    :param settings: the loaded settings.
    :return: the wiring for ``discover.execute_discovery``.
    :raises errors.ConfigError: when a model, router or tracer setting
        is unusable.
    """
    clients = litecli.build_clients(settings.discovery)
    executor_model = clients.models["executor"]
    wiring = discover.ModelWiring(
        llm=clients.executor,
        model_name=executor_model,
        token_counter=litecli.LiteLlmTokenCounter(executor_model),
        tracer=aofactor.tracer(settings.observability),
        scrubber=apfactor.scrubber(settings.privacy),
        role_llms=clients.roles,
        role_models=clients.models,
    )
    return wiring
