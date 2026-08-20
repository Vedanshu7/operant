"""
Target strategies and parameterised values.

A target is a ranked stack of strategies; replay tries each in order
against the screen digest until one resolves to exactly one control. A
``Value`` is how an edge's typed text is parameterised at recording
time: a literal, a task input, a secret reference, or dataflow from an
earlier output.

Import as:

import operant.domain.models.targets as targets
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional, Union

import pydantic

# #############################################################################
# RoleStrategy
# #############################################################################


class RoleStrategy(pydantic.BaseModel):
    """
    Match a control by accessibility role and name.

    :ivar kind: Discriminator, always ``role``.
    :ivar role: Accessibility role to match.
    :ivar name: Accessible name to match.
    """

    kind: Literal["role"] = "role"
    role: str
    name: str


# #############################################################################
# LabelProximityStrategy
# #############################################################################


class LabelProximityStrategy(pydantic.BaseModel):
    """
    Match a control of a role that sits next to anchoring text.

    :ivar kind: Discriminator, always ``labelProximity``.
    :ivar anchor_text: Nearby text that labels the control.
    :ivar role: Accessibility role of the control.
    """

    kind: Literal["labelProximity"] = "labelProximity"
    anchor_text: str
    role: str


# #############################################################################
# StructuralStrategy
# #############################################################################


class StructuralStrategy(pydantic.BaseModel):
    """
    Match a control by its accessibility tree path.

    :ivar kind: Discriminator, always ``structural``.
    :ivar path: A11y tree path, e.g.
        ``window>group:1>table>row:3>link``.
    """

    kind: Literal["structural"] = "structural"
    path: str


# #############################################################################
# RegionStrategy
# #############################################################################


class RegionStrategy(pydantic.BaseModel):
    """
    Match a control of a role near a window-normalised position.

    :ivar kind: Discriminator, always ``region``.
    :ivar role: Accessibility role of the control.
    :ivar x: Expected left edge, 0..1.
    :ivar y: Expected top edge, 0..1.
    :ivar w: Expected width, 0..1.
    :ivar h: Expected height, 0..1.
    :ivar tolerance: Allowed positional drift, 0..1.
    """

    kind: Literal["region"] = "region"
    role: str
    x: float
    y: float
    w: float
    h: float
    tolerance: float = 0.08


TargetStrategy = Annotated[
    Union[
        RoleStrategy, LabelProximityStrategy, StructuralStrategy, RegionStrategy
    ],
    pydantic.Field(discriminator="kind"),
]


# #############################################################################
# Target
# #############################################################################


class Target(pydantic.BaseModel):
    """
    A ranked stack of strategies that names one control.

    :ivar strategies: Strategies tried in order; at least one.
    :ivar reasoning: Why the recorder chose this stack.
    """

    strategies: List[TargetStrategy] = pydantic.Field(min_length=1)
    reasoning: str


# #############################################################################
# Value
# #############################################################################


class Value(pydantic.BaseModel):
    """
    Exactly one of literal / param / secret_ref / from_output.

    Secrets are references resolved from the environment at replay; the
    value itself never enters an artifact, log, or model prompt.
    ``from_output`` is dataflow: the value extracted earlier in the run
    under that output name (e.g. a balance read in one app, typed into
    another).

    :ivar literal: Fixed text recorded as-is.
    :ivar param: Name of the task input supplying the text.
    :ivar secret_ref: Name of the tenant secret supplying the text.
    :ivar from_output: Name of an earlier output supplying the text.
    """

    literal: Optional[str] = None
    param: Optional[str] = None
    secret_ref: Optional[str] = None
    from_output: Optional[str] = None

    @pydantic.model_validator(mode="after")
    def _exactly_one(self) -> Value:
        """
        Reject values that set zero or several sources.
        """
        set_fields = [
            v
            for v in (
                self.literal,
                self.param,
                self.secret_ref,
                self.from_output,
            )
            if v is not None
        ]
        if len(set_fields) != 1:
            raise ValueError(
                "Value must set exactly one of "
                "literal/param/secret_ref/from_output"
            )
        return self
