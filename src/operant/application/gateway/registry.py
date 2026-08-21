"""
Tool registry and per-action-kind chain configuration.

Chains are ordered preference lists loaded from the gateway policy JSON.
A tool registered but absent from a chain is never dispatched; a chain
entry with no registered tool is a configuration error raised at
startup, not mid-run.

Import as:

import operant.application.gateway.registry as grregist
"""

from __future__ import annotations

import pathlib
from typing import Dict, List

import pydantic

import operant.domain.errors as errors
import operant.helpers.files as files
import operant.ports.tool as pttool

# #############################################################################
# GatewayConfig
# #############################################################################


class GatewayConfig(pydantic.BaseModel):
    """
    The tool chains, keyed by action kind.

    :ivar chains: Ordered tool names to try for each action kind.
    """

    chains: Dict[str, List[str]]


def load_gateway_config(path: pathlib.Path) -> GatewayConfig:
    """
    Load and validates the gateway chain configuration.

    :param path: The gateway policy JSON file.
    :return: The parsed configuration.
    """
    config = files.read_model(path, GatewayConfig)
    return config


# #############################################################################
# ToolRegistry
# #############################################################################


class ToolRegistry:
    """
    Hold the registered tools and resolves chains against them.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, pttool.Tool] = {}

    def register(self, tool: pttool.Tool) -> None:
        """
        Add a tool.
        """
        if tool.spec.name in self._tools:
            raise errors.ConfigError(
                f'tool "{tool.spec.name}" is already registered'
            )
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> pttool.Tool:
        """
        Return a registered tool by name.
        """
        if name not in self._tools:
            raise errors.ConfigError(f'no tool named "{name}" is registered')
        tool = self._tools[name]
        return tool

    def all(self) -> List[pttool.Tool]:
        """
        Return every registered tool.
        """
        registered = list(self._tools.values())
        return registered

    def chain_for(self, kind: str, config: GatewayConfig) -> List[pttool.Tool]:
        """
        Resolve the tool chain for one action kind.
        """
        chain: List[pttool.Tool] = []
        for name in config.chains.get(kind, []):
            tool = self.get(name)
            if kind not in tool.spec.serves:
                raise errors.ConfigError(
                    f'tool "{name}" does not serve action kind "{kind}"'
                )
            chain.append(tool)
        return chain

    def validate(self, config: GatewayConfig) -> None:
        """
        Check every chain resolves; raises ``ConfigError`` otherwise.
        """
        for kind in config.chains:
            self.chain_for(kind, config)
