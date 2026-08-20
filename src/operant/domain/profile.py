"""App profile: per-vendor knowledge shared by every capability.

Where the application runs, its policy, tenant bindings, and the
app-wide outcome edges (session loss, auth failure, error pages). File
I/O belongs to a repository; this module only defines the shape.

Import as:

import operant.domain.profile as profile
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pydantic

import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.domain.policy as dmpolicy

# #############################################################################
# FaultInjection
# #############################################################################


class FaultInjection(pydantic.BaseModel):
    """
    How to knock over this app's backend for a session-expiry demo.

    Absent for apps we do not control; fault injection then refuses to
    run.

    :ivar restart_cmd: Command that restarts the backend.
    :ivar health_url: URL polled until the backend is back.
    :ivar timeout_s: How long to wait for the backend to return.
    """

    restart_cmd: List[str]
    health_url: str
    timeout_s: int = 180


# #############################################################################
# AppProfile
# #############################################################################


class AppProfile(pydantic.BaseModel):
    """
    Per-vendor configuration every capability against the app shares.

    :ivar vendor_id: Application identifier the profile belongs to.
    :ivar app_name: OS application that hosts the target (e.g. ``Google
        Chrome``).
    :ivar window_title_pattern: Regex the driven window's title matches.
    :ivar policy: The policy capabilities against this app run under.
    :ivar tenants: Tenant bindings keyed by tenant name.
    :ivar default_tenant: Tenant used when a run names none.
    :ivar global_outcome_edges: App-wide detectors applied at every
        node.
    :ivar fault_injection: Backend fault injection, when supported.
    """

    vendor_id: str
    app_name: str
    window_title_pattern: str
    policy: dmpolicy.Policy
    tenants: Dict[str, artifact.TenantBinding]
    default_tenant: str
    global_outcome_edges: List[graph.OutcomeEdge] = []
    fault_injection: Optional[FaultInjection] = None

    @classmethod
    def from_json_text(cls, text: str) -> AppProfile:
        """
        Validate a profile from its JSON document text.

        :param text: The JSON document, as read from a profile file.
        :return: The validated profile.
        """
        profile = cls.model_validate_json(text)
        return profile
