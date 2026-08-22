import pathlib

import operant.infra.settings as issettin
import tests.support.settings as sssettin


def test_relative_paths_resolve_under_root(tmp_path: pathlib.Path) -> None:
    settings = sssettin.test_settings(tmp_path)
    assert settings.paths.graphs_dir == tmp_path / "graphs"
    assert settings.paths.db_path == tmp_path / "state" / "operant.sqlite3"
    assert settings.paths.chrome_profile_dir.is_absolute()
    assert "~" not in str(settings.paths.chrome_profile_dir)


def test_nested_env_overrides_and_legacy_aliases(
    monkeypatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("OPERANT_SERVER__PORT", "9090")
    monkeypatch.setenv("OPERANT_ENGINE__TOTAL_TIMEOUT_S", "12.5")
    monkeypatch.setenv("CUA_DRIVER_URL", "http://127.0.0.1:7411")
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-haiku-4-5")
    monkeypatch.setenv("CUA_APPROVAL_TIMEOUT_S", "15")
    settings = issettin.OperantSettings.load(root=tmp_path)
    assert settings.server.port == 9090
    assert settings.engine.total_timeout_s == 12.5
    assert settings.driver.url == "http://127.0.0.1:7411"
    assert settings.discovery.model == "anthropic/claude-haiku-4-5"
    assert settings.approval.timeout_s == 15


def test_defaults_match_the_documented_ports(tmp_path: pathlib.Path) -> None:
    settings = sssettin.test_settings(tmp_path)
    assert (settings.server.port, settings.driver.port) == (7080, 7411)
    assert settings.governance.min_runs == 3
    assert settings.governance.min_success_rate == 0.8
    assert settings.browser.allow_applescript_fill is False
    assert settings.secrets.backend == "env"
