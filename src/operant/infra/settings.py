"""Typed configuration for every process Operant runs.

Values come from the environment (prefix ``OPERANT_``, nested groups
separated by ``__``) and an optional ``.env`` file. Only the composition
roots - the CLI entry point and the server factory - call
``OperantSettings.load``; everything else receives the sub-group it needs
through its constructor, so no module reads ``os.environ`` on its own.

Typical usage example:

  settings = OperantSettings.load()
  launcher = AppLauncher(settings.browser, settings.paths.chrome_profile_dir)

Import as:

import operant.infra.settings as issettin
"""

from __future__ import annotations

import collections.abc
import os
import pathlib
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Self, Tuple

import dotenv
import pydantic
import pydantic_settings

_DEFAULT_BROWSER_BINARIES: Tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


# #############################################################################
# PathsSettings
# #############################################################################


class PathsSettings(pydantic.BaseModel):
    """
    Where Operant keeps its data; relative paths resolve under ``root``.

    :ivar root: Base directory for every relative path below.
    :ivar graphs_dir: Versioned app graphs.
    :ivar artifacts_dir: Versioned capability artifacts.
    :ivar policies_dir: App profiles (policy + tenants).
    :ivar evidence_dir: Run logs and screenshots.
    :ivar state_dir: Machine-local state (database, learned tools).
    :ivar db_path: SQLite database file.
    :ivar discovery_base_profile: Deny-by-default profile for bootstrap
        runs.
    :ivar gateway_policy: Tool fallback chain configuration.
    :ivar learned_tools: Learned tool preference cache.
    :ivar chrome_profile_dir: Dedicated automation browser profile.
    """

    root: pathlib.Path = pydantic.Field(default_factory=pathlib.Path.cwd)
    graphs_dir: pathlib.Path = pathlib.Path("graphs")
    artifacts_dir: pathlib.Path = pathlib.Path("artifacts")
    policies_dir: pathlib.Path = pathlib.Path("policies")
    evidence_dir: pathlib.Path = pathlib.Path("evidence")
    state_dir: pathlib.Path = pathlib.Path("state")
    db_path: pathlib.Path = pathlib.Path("state/operant.sqlite3")
    discovery_base_profile: pathlib.Path = pathlib.Path(
        "policies/discovery-base.json"
    )
    gateway_policy: pathlib.Path = pathlib.Path("policies/gateway.json")
    learned_tools: pathlib.Path = pathlib.Path("state/learned-tools.json")
    remediations: pathlib.Path = pathlib.Path("state/remediations.json")
    chrome_profile_dir: pathlib.Path = pathlib.Path("~/.operant/chrome-profile")

    @pydantic.model_validator(mode="after")
    def _resolve(self) -> Self:
        """
        Expand ``~`` and anchors relative paths under ``root``.
        """
        root = self.root.expanduser().resolve()
        self.root = root
        for name in (
            "graphs_dir",
            "artifacts_dir",
            "policies_dir",
            "evidence_dir",
            "state_dir",
            "db_path",
            "discovery_base_profile",
            "gateway_policy",
            "learned_tools",
            "remediations",
            "chrome_profile_dir",
        ):
            value = getattr(self, name).expanduser()
            if not value.is_absolute():
                value = root / value
            setattr(self, name, value)
        return self


# #############################################################################
# ServerSettings
# #############################################################################


class ServerSettings(pydantic.BaseModel):
    """
    The operator-facing HTTP server.

    :ivar host: Bind address.
    :ivar port: Bind port.
    :ivar auth_token: Bearer token required on every API route.
    :ivar cors_origins: Origins allowed during frontend development.
    :ivar static_dir: Built frontend to serve at ``/``; ``None``
        disables it.
    :ivar log_format:``"text"`` or ``"json"`` log lines.
    """

    host: str = "127.0.0.1"
    port: int = 7080
    auth_token: Optional[pydantic.SecretStr] = None
    cors_origins: List[str] = ["http://localhost:5173"]
    static_dir: Optional[pathlib.Path] = None
    log_format: Literal["text", "json"] = "text"


# #############################################################################
# DriverSettings
# #############################################################################


class DriverSettings(pydantic.BaseModel):
    """
    The driver daemon that owns the OS automation permissions.

    :ivar host: Bind address when serving the daemon.
    :ivar port: Bind port when serving the daemon.
    :ivar url: Daemon URL for clients; ``None`` means in-process
        surface.
    :ivar auth_token: Bearer token shared by daemon and clients.
    :ivar lease_timeout_s: How long a run may wait for the driver.
    """

    host: str = "127.0.0.1"
    port: int = 7411
    url: Optional[str] = None
    auth_token: Optional[pydantic.SecretStr] = None
    lease_timeout_s: float = 600.0


# #############################################################################
# EngineSettings
# #############################################################################


class EngineSettings(pydantic.BaseModel):
    """
    Deterministic replay timing and budgets.

    :ivar total_timeout_s: Wall-clock budget per replay (human waits
        excluded).
    :ivar poll_interval_s: Delay between node-arrival polls.
    :ivar recovery_budget: Re-login recoveries allowed per replay.
    :ivar retry_delay_s: Pause before retrying a locator or edge.
    :ivar settle_ms: Minimum settle wait after an action.
    :ivar settle_short_ms: Short settle wait for fast edges.
    :ivar goal_poll_s: Extra time to wait for the goal node.
    :ivar max_invoke_depth: Cross-graph composition depth limit.
    """

    total_timeout_s: float = 240.0
    poll_interval_s: float = 0.6
    recovery_budget: int = 2
    retry_delay_s: float = 1.5
    settle_ms: int = 4000
    settle_short_ms: int = 2000
    goal_poll_s: float = 6.0
    max_invoke_depth: int = 4


# #############################################################################
# DiscoverySettings
# #############################################################################


class DiscoverySettings(pydantic.BaseModel):
    """
    LLM discovery configuration.

    :ivar model: litellm model string.
    :ivar api_base: OpenAI-compatible base URL, when proxied.
    :ivar api_key: API key for ``api_base`` providers.
    :ivar max_turns: Turn budget per discovery run.
    :ivar llm_retries: Attempts per model call.
    :ivar screenshots: Whether to send screenshots to the model.
    """

    model: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[pydantic.SecretStr] = None
    max_turns: int = 40
    llm_retries: int = 3
    screenshots: bool = True


# #############################################################################
# ApprovalSettings
# #############################################################################


class ApprovalSettings(pydantic.BaseModel):
    """
    How long the system waits for a human.

    :ivar timeout_s: Approval wait; a timeout is a denial.
    :ivar clarification_timeout_s: Clarifying-question wait.
    :ivar intervention_timeout_s: Control-transfer wait; ``None`` is
        unbounded.
    """

    timeout_s: float = 300.0
    clarification_timeout_s: float = 300.0
    intervention_timeout_s: Optional[float] = None


# #############################################################################
# GovernanceSettings
# #############################################################################


class GovernanceSettings(pydantic.BaseModel):
    """
    The approval gate for unattended replay.

    :ivar min_runs: Replays required before a capability can be
        approved.
    :ivar min_success_rate: Success ratio required over those replays.
    """

    min_runs: int = 3
    min_success_rate: float = 0.8


# #############################################################################
# BrowserSettings
# #############################################################################


class BrowserSettings(pydantic.BaseModel):
    """
    Browser-specific knowledge the adapters need.

    :ivar default_app: App used when a goal names only a URL.
    :ivar browser_app_names: Lower-cased app names treated as browsers.
    :ivar binaries: Candidate browser executables, first match wins.
    :ivar local_hosts: Hostnames treated as local for vendor derivation.
    :ivar allow_applescript_fill: Permit the keystroke fill tool, which
        exposes typed text in the process table.
    """

    default_app: str = "Google Chrome"
    browser_app_names: FrozenSet[str] = frozenset(
        {"google chrome", "chromium", "safari", "firefox", "arc"}
    )
    binaries: Tuple[str, ...] = _DEFAULT_BROWSER_BINARIES
    local_hosts: FrozenSet[str] = frozenset({"localhost", "127.0.0.1"})
    allow_applescript_fill: bool = False


# #############################################################################
# SecretsSettings
# #############################################################################


class SecretsSettings(pydantic.BaseModel):
    """
    Where secret reference values come from.

    :ivar backend:``"env"`` or ``"keychain"``.
    :ivar keychain_service: Service name for Keychain items.
    """

    backend: Literal["env", "keychain"] = "env"
    keychain_service: str = "operant"


# #############################################################################
# OperantSettings
# #############################################################################


class OperantSettings(pydantic_settings.BaseSettings):
    """
    Root settings object; see module docstring for sourcing rules.
    """

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="OPERANT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    paths: PathsSettings = PathsSettings()
    server: ServerSettings = ServerSettings()
    driver: DriverSettings = DriverSettings()
    engine: EngineSettings = EngineSettings()
    discovery: DiscoverySettings = DiscoverySettings()
    approval: ApprovalSettings = ApprovalSettings()
    governance: GovernanceSettings = GovernanceSettings()
    browser: BrowserSettings = BrowserSettings()
    secrets: SecretsSettings = SecretsSettings()
    log_level: str = "INFO"
    legacy_sources: List[str] = []

    @classmethod
    def load(
        cls,
        *,
        root: Optional[pathlib.Path] = None,
        env_file: Optional[pathlib.Path] = None,
    ) -> OperantSettings:
        """
        Build settings from the environment and an optional ``.env``.

        Legacy variable names from the ``cua`` era (``CUA_DRIVER_URL``,
        ``LLM_MODEL``, ...) are honoured when their ``OPERANT_`` form is
        unset; ``legacy_sources`` records which ones were used so
        ``operant doctor`` can warn.

        :param root: Overrides ``paths.root``; defaults to the working
            directory.
        :param env_file: Overrides the ``.env`` location.
        :return: The validated settings.
        """
        if env_file is not None:
            # Load an explicitly named env file.
            dotenv.load_dotenv(env_file, override=False)
        elif pathlib.Path(".env").exists():
            # Otherwise load a .env from the working directory.
            dotenv.load_dotenv(".env", override=False)
        overrides: Dict[str, Any] = dict(_legacy_overrides(os.environ))
        if root is not None:
            overrides.setdefault("paths", {})["root"] = root
        settings = cls(**overrides)
        settings.legacy_sources = [
            legacy
            for legacy, (_, _, modern) in _LEGACY_ENV.items()
            if legacy in os.environ and modern not in os.environ
        ]
        return settings


_LEGACY_ENV: Dict[str, Tuple[str, str, str]] = {
    "CUA_DRIVER_URL": ("driver", "url", "OPERANT_DRIVER__URL"),
    "CUA_APPROVAL_TIMEOUT_S": (
        "approval",
        "timeout_s",
        "OPERANT_APPROVAL__TIMEOUT_S",
    ),
    "LLM_MODEL": ("discovery", "model", "OPERANT_DISCOVERY__MODEL"),
    "LLM_BASE_URL": ("discovery", "api_base", "OPERANT_DISCOVERY__API_BASE"),
    "LLM_API_KEY": ("discovery", "api_key", "OPERANT_DISCOVERY__API_KEY"),
}


def _legacy_overrides(
    environ: collections.abc.Mapping[str, str],
) -> Dict[str, Dict[str, Any]]:
    """
    Map legacy variable names onto nested settings overrides.

    :param environ: The process environment.
    :return:``{group: {field: value}}`` for every legacy name that is
        set while its modern equivalent is not.
    """
    overrides: Dict[str, Dict[str, Any]] = {}
    for legacy, (group, field, modern) in _LEGACY_ENV.items():
        if legacy in environ and modern not in environ:
            overrides.setdefault(group, {})[field] = environ[legacy]
    return overrides
