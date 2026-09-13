"""
Screenshots black out sensitive fields before they reach the model or the
evidence directory.
"""

import dataclasses
import pathlib
from typing import Optional, cast

import PIL.Image

import operant.application.gateway.adapter as adapter
import operant.application.gateway.guard as guard
import operant.domain.models.digest as digest
import operant.domain.policy as policy
import tests.support.screens as screens

POLICY = policy.Policy(
    id="p",
    allowed_apps=[],
    allowed_url_patterns=[],
    allowed_action_kinds=[],
    mutating_control_patterns=[],
)
PASSWORD_BOX = digest.Box(0.5, 0.5, 0.25, 0.25)
SEARCH_BOX = digest.Box(0.0, 0.0, 0.25, 0.25)
SCREEN = screens.digest(
    controls=(
        screens.control(
            "p", "text_field", label="Password", value="••••", box=PASSWORD_BOX
        ),
        screens.control("s", "text_field", label="Search", box=SEARCH_BOX),
    )
)


# #############################################################################
# StubGateway
# #############################################################################


@dataclasses.dataclass
class StubGateway:
    policy: policy.Policy
    last_digest: Optional[digest.ScreenDigest]


# #############################################################################
# WhiteWindowSession
# #############################################################################


class WhiteWindowSession:
    """
    Captures a 100x100 all-white window.
    """

    def screenshot(self, path: str) -> bool:
        PIL.Image.new("RGB", (100, 100), (255, 255, 255)).save(path)
        return True


def _shoot(tmp_path: pathlib.Path, screen) -> PIL.Image.Image:
    gateway = cast(guard.GuardedGateway, StubGateway(POLICY, screen))
    surface = adapter.GatewaySurface(gateway, WhiteWindowSession())
    path = tmp_path / "shot.png"
    assert surface.screenshot(path)
    return PIL.Image.open(path).convert("RGB")


def test_a_password_field_is_blacked_out_and_the_rest_is_kept(tmp_path):
    image = _shoot(tmp_path, SCREEN)
    assert image.getpixel((60, 60)) == (0, 0, 0)
    assert image.getpixel((10, 10)) == (255, 255, 255)
    assert image.getpixel((95, 5)) == (255, 255, 255)


def test_nothing_is_masked_before_the_first_observation(tmp_path):
    image = _shoot(tmp_path, None)
    assert image.getpixel((60, 60)) == (255, 255, 255)


def test_policy_field_patterns_are_masked_too():
    custom = POLICY.model_copy(
        update={
            "approval": POLICY.approval.model_copy(
                update={"sensitive_field_patterns": ["member number"]}
            )
        }
    )
    member = screens.control(
        "m", "text_field", label="Member number", box=SEARCH_BOX
    )
    assert policy.sensitive_boxes(custom, screens.digest(controls=(member,))) == [
        SEARCH_BOX
    ]
    assert (
        policy.sensitive_boxes(POLICY, screens.digest(controls=(member,))) == []
    )
