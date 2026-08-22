"""
Shared builders for recorder, capabilities, and segmentation tests.
"""

from __future__ import annotations

from typing import Dict, Optional

import operant.application.recorder.builder as builder
import operant.application.recorder.recording as recdng
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.profile as profile

PROFILE = profile.AppProfile(
    vendor_id="acme",
    app_name="Google Chrome",
    window_title_pattern="Acme",
    policy=policy.Policy(
        id="acme",
        allowed_apps=["Google Chrome"],
        allowed_url_patterns=[".*"],
        allowed_action_kinds=["launch", "click", "fill", "press"],
        mutating_control_patterns=[],
    ),
    tenants={
        "t": artifact.TenantBinding(base_url="http://localhost:1", secret_refs={})
    },
    default_tenant="t",
)


def control(name: str, role: str = "link") -> digest.Control:
    """
    Build a simple control with the given accessible name.
    """
    return digest.Control(
        ref="c1",
        role=role,
        name=name,
        label="",
        path=f"window>{role}",
        box=digest.Box(0.1, 0.1, 0.2, 0.05),
    )


def record(
    recorder: recdng.Recorder,
    *,
    action: graph.Action,
    control: Optional[digest.Control],
    description: str,
    pre: str,
    post: str,
) -> None:
    """
    Record one safe action between two window titles.
    """
    recorder.record(
        action=action,
        target_control=control,
        description=description,
        risk="safe",
        pre_title=pre,
        post_title=post,
    )


def build_recording(
    recorder: recdng.Recorder,
    inputs: Dict[str, str],
    outputs: Dict[str, str],
    *,
    capability_id: str = "cap",
    goal: str = "g",
    run_id: str = "r",
    input_classes: Optional[Dict[str, str]] = None,
) -> recdng.Recording:
    """
    Build a recording with the shared test profile.
    """
    return builder.build(
        recorder,
        profile=PROFILE,
        capability_id=capability_id,
        capability_name=capability_id,
        goal=goal,
        inputs=inputs,
        outputs=outputs,
        model="m",
        run_id=run_id,
        input_classes=input_classes,
    )
