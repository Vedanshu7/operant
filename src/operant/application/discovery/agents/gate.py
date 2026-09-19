"""
The model judge for unknown controls.

Discovery explores controls no policy pattern names. The judge decides
whether a person should see one first. It can only tighten the policy:
anything but a clear ``navigation`` asks a person, and a failed call counts
as ``unsure``. Screen text reaches it as fenced, untrusted data.

Import as:

import operant.application.discovery.agents.gate as dagate
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, cast

import operant.application.discovery.agents.consult as consult
import operant.domain.digest as odigest
import operant.domain.events as events
import operant.domain.fingerprint as odfinger
import operant.domain.injection as odinject
import operant.domain.models.digest as digest

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop

Verdict = Literal["navigation", "commit", "unsure"]

_VERDICTS: Final = frozenset({"navigation", "commit", "unsure"})


def judge(
    session: loop.DiscoverySession,
    control: digest.Control,
    screen: digest.ScreenDigest,
    *,
    turn: int,
) -> Verdict:
    """
    Classify a control, once per role and name in a run.

    :param session: the discovery session.
    :param control: the control about to be clicked.
    :param screen: the screen it is on.
    :param turn: the executor turn this call belongs to.
    :return: the verdict; ``unsure`` when the model gave no usable
        answer.
    """
    key = f"{control.role}|{odfinger.normalize(control.name)}"
    cached = session.judged.get(key)
    if cached is not None:
        return cast(Verdict, cached)
    text = session.safe_text(
        f"Control: role={control.role} name={control.name!r}\n"
        f"{odinject.fence(odigest.render_digest(screen))}"
    )
    answer = consult.ask(session, "gate", text, turn=turn) or {}
    kind = str(answer.get("kind", ""))
    verdict = cast(Verdict, kind if kind in _VERDICTS else "unsure")
    session.judged[key] = verdict
    session.log.emit(
        events.ControlJudged(
            role=control.role,
            name=control.name,
            verdict=verdict,
            summary=f'judge: {control.role} "{control.name}" is {verdict}',
        )
    )
    return verdict
