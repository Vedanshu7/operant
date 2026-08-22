"""
Vendor bootstrap: identity derivation, scope proposals, generated profiles.
"""

import json
import pathlib
import re

import operant.application.discovery.bootstrap as bstrap
import operant.domain.approval as approval
import operant.domain.models.actions as actions
import operant.domain.policy as policy
import operant.domain.profile as profile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _base_profile() -> profile.AppProfile:
    raw = (REPO_ROOT / "policies" / "discovery-base.json").read_text()
    return profile.AppProfile.model_validate(json.loads(raw))


def test_native_app_vendor_is_the_app() -> None:
    boot = bstrap.derive_vendor("WhatsApp", None)
    assert boot.vendor_id == "whatsapp"
    assert boot.app_name == "WhatsApp"


def test_web_vendor_is_the_registrable_domain() -> None:
    boot = bstrap.derive_vendor("Google Chrome", "https://web.whatsapp.com/chats")
    assert boot.vendor_id == "whatsapp"
    assert boot.app_name == "Google Chrome"


def test_localhost_vendor_from_path() -> None:
    boot = bstrap.derive_vendor(
        "Google Chrome", "http://localhost:8080/parabank/index.htm"
    )
    assert boot.vendor_id == "parabank"


def test_scheme_url_vendor() -> None:
    boot = bstrap.derive_vendor(
        "System Settings",
        "x-apple.systempreferences:com.apple.Displays-Settings",
    )
    assert boot.vendor_id == "system-settings"


def test_propose_scope_url_covers_whole_domain() -> None:
    request = policy.propose_scope(
        actions.SurfaceAction(kind="launch", url="https://web.whatsapp.com/send"),
        "send a message",
    )
    assert request is not None and request.kind == "url"
    assert re.search(request.proposed, "https://web.whatsapp.com/anything")
    assert re.search(request.proposed, "https://whatsapp.com/")
    assert not re.search(request.proposed, "https://evil.com/web.whatsapp.com")


def test_propose_scope_app_is_exact() -> None:
    request = policy.propose_scope(
        actions.SurfaceAction(kind="launch", app="Notes"), "create a note"
    )
    assert request is not None and request.kind == "app"
    assert request.proposed == "Notes"


def test_generated_profile_folds_grants_into_policy() -> None:
    base = _base_profile()
    boot = bstrap.derive_vendor("Notes", None)
    grants = [approval.ScopeGrant(kind="app", pattern="Notes", reason="r")]
    generated = bstrap.profile_for(boot, base, grants)
    assert generated.vendor_id == "notes"
    assert "Notes" in generated.policy.allowed_apps
    assert generated.policy.id == "notes"
    assert generated.default_tenant == "default"
    # The approval gates survive generation.
    assert generated.policy.approval.sensitive_fill != "off"
    assert generated.policy.approval.mutating
