import pytest

import operant.adapters.secrets.env as env
import operant.application.actions as actions
import operant.application.secrets as secrets
import operant.domain.models.artifact as artifact
import operant.domain.redaction as redact


def _factory_with_secret() -> actions.ActionFactory:
    tenant = artifact.TenantBinding(
        base_url="http://x", secret_refs={"password": "APP_PW"}
    )
    resolver = secrets.SecretResolver(
        tenant, env.EnvSecretStore({"APP_PW": "hunter2"}), redact.Redactor()
    )
    return actions.ActionFactory(resolver)


def test_launch_click_press_pairs() -> None:
    factory = actions.ActionFactory()
    launch = factory.launch("Google Chrome", "http://x/", step="e1")
    assert launch.surface.kind == "launch" and launch.surface.step == "e1"
    assert launch.recorded is not None and launch.recorded.url == "http://x/"
    click = factory.click("c1", step="e2")
    assert click.surface.ref == "c1" and click.recorded.kind == "click"
    at = factory.click_at(0.5, 0.6)
    assert at.surface.x == 0.5 and at.surface.y == 0.6
    press = factory.press("Enter")
    assert press.surface.key == "Enter" and press.recorded.key == "Enter"


def test_fill_records_a_literal_by_default() -> None:
    factory = actions.ActionFactory()
    pair = factory.fill("c1", "12456", data_class="none", step="e3")
    assert pair.surface.value == "12456" and pair.surface.data_class == "none"
    assert pair.recorded.value is not None
    assert pair.recorded.value.literal == "12456"


def test_fill_secret_resolves_and_records_only_the_reference() -> None:
    pair = _factory_with_secret().fill_secret("pw", "password", step="e4")
    assert pair.surface.value == "hunter2"
    assert pair.surface.secret_ref == "password"
    assert pair.surface.data_class == "credential"
    assert pair.recorded.value is not None
    assert pair.recorded.value.secret_ref == "password"
    assert pair.recorded.value.literal is None


def test_fill_secret_without_resolver_raises() -> None:
    with pytest.raises(RuntimeError):
        actions.ActionFactory().fill_secret("pw", "password")


def test_select_and_scroll() -> None:
    factory = actions.ActionFactory()
    select = factory.select("c1", "Checking", step="e5")
    assert select.surface.option == "Checking"
    assert select.recorded.option is not None
    assert select.recorded.option.literal == "Checking"
    scroll = factory.scroll("c1", "down", 3)
    assert scroll.surface.direction == "down" and scroll.surface.amount == 3
    assert scroll.recorded.direction == "down"
