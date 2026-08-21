"""
Vendor bootstrap: derive an application's identity from what was opened.

A brand-new app gets its vendor id, graph binding, and a replayable
profile from a single discovery run - nothing pre-seeded. Which app
names count as browsers, and which hosts as local, comes from settings
rather than being baked in.

Import as:

import operant.application.discovery.bootstrap as bstrap
"""

from __future__ import annotations

import re
import urllib.parse
from typing import FrozenSet, List, Optional

import pydantic

import operant.domain.approval as approval
import operant.domain.models.artifact as artifact
import operant.domain.policy as policy
import operant.domain.profile as profile
import operant.helpers.text as httext

DEFAULT_BROWSERS: FrozenSet[str] = frozenset(
    {"google chrome", "chromium", "safari", "firefox", "arc"}
)


# #############################################################################
# VendorBootstrap
# #############################################################################


class VendorBootstrap(pydantic.BaseModel):
    """
    The identity derived from a first launch.

    :ivar vendor_id: Graph and profile id for the application.
    :ivar app_name: OS application hosting it.
    :ivar window_title_pattern:``".*"`` for a generated binding - the
        dedicated automation instance hosts only our windows, so the
        app-level pattern need not narrow further.
    :ivar entry_url: The URL that was opened, when any.
    """

    vendor_id: str
    app_name: str
    window_title_pattern: str = ".*"
    entry_url: Optional[str] = None


def _slug(text: str) -> str:
    """
    Slugify text, or fall back to ``app`` when it is blank.
    """
    slug = httext.slugify(text) if text.strip() else "app"
    return slug


def derive_vendor(
    app_name: str,
    url: Optional[str],
    *,
    browsers: FrozenSet[str] = DEFAULT_BROWSERS,
    local_hosts: FrozenSet[str] = policy.DEFAULT_LOCAL_HOSTS,
) -> VendorBootstrap:
    """
    Derive the vendor identity from the launch the model decided on.

    The registrable domain for web targets (the app is just the browser
    hosting it), the application itself for native ones.

    :param app_name: The launched application.
    :param url: The opened URL, when any.
    :param browsers: Lower-cased app names treated as browsers.
    :param local_hosts: Hostnames treated as local (vendor from the
        path).
    :return: The derived identity.
    """
    if url and app_name.lower() in browsers and url.startswith("http"):
        # Web target: the registrable domain names the vendor, not the browser.
        domain = policy.registrable_domain(url, local_hosts=local_hosts) or "web"
        if domain in local_hosts or re.fullmatch(r"[\d.]+", domain):
            path_seg = urllib.parse.urlparse(url).path.strip("/").split("/")[0]
            vendor = _slug(path_seg or domain)
        else:
            vendor = _slug(domain.split(".")[0])
        boot = VendorBootstrap(vendor_id=vendor, app_name=app_name, entry_url=url)
    elif url and not url.startswith("http"):
        # A URL scheme (x-apple.systempreferences:, mailto:, ...) - the OS
        # routes it; the scheme names the owning surface.
        scheme = url.split(":", 1)[0]
        boot = VendorBootstrap(
            vendor_id=_slug(app_name or scheme),
            app_name=app_name,
            entry_url=url,
        )
    else:
        # Native app or bare launch: the application itself is the vendor.
        boot = VendorBootstrap(
            vendor_id=_slug(app_name), app_name=app_name, entry_url=url
        )
    return boot


def profile_for(
    boot: VendorBootstrap,
    base: profile.AppProfile,
    grants: List[approval.ScopeGrant],
) -> profile.AppProfile:
    """
    Build the replayable profile a bootstrap discovery leaves behind.

    The base discovery policy widened by exactly the scopes a human
    granted.

    :param boot: The derived vendor identity.
    :param base: The deny-by-default discovery profile.
    :param grants: Scope grants made during the run.
    :return: A profile that replays the recording without re-approval.
    """
    app_grants = {g.pattern for g in grants if g.kind == "app"}
    url_grants = {g.pattern for g in grants if g.kind == "url"}
    widened = base.policy.model_copy(
        update={
            "id": boot.vendor_id,
            "allowed_apps": sorted(
                {*base.policy.allowed_apps, boot.app_name, *app_grants} - {""}
            ),
            "allowed_url_patterns": sorted(
                {*base.policy.allowed_url_patterns, *url_grants}
            ),
        }
    )
    result = profile.AppProfile(
        vendor_id=boot.vendor_id,
        app_name=boot.app_name,
        window_title_pattern=boot.window_title_pattern,
        policy=widened,
        tenants={
            "default": artifact.TenantBinding(base_url=boot.entry_url or "")
        },
        default_tenant="default",
        global_outcome_edges=base.global_outcome_edges,
    )
    return result
