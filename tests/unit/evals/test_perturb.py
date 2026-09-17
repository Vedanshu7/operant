"""
Replay under UI changes (no model).

It never acts on the wrong control, still recognizes the screen, and the
recognition threshold is justified.
"""

import pytest

import tests.evals.perturb as evpertur

_SCORES = evpertur.evaluate()


@pytest.mark.parametrize("change", sorted(evpertur.OPERATORS))
def test_a_ui_change_never_makes_replay_act_on_another_control(
    change: str,
) -> None:
    score = _SCORES[change]
    assert score.wrong == 0
    assert score.correct + score.escalated == score.targets


@pytest.mark.parametrize("change", sorted(evpertur.OPERATORS))
def test_a_ui_change_never_locates_another_screen(change: str) -> None:
    assert _SCORES[change].wrong_screens == 0


def test_nearly_every_changed_screen_is_still_located() -> None:
    located = [ok for score in _SCORES.values() for ok in score.located]
    assert sum(located) >= 190
    assert len(located) == 195


def test_coverage_alone_never_picks_another_screen_at_the_shipped_threshold() -> (
    None
):
    cases = [case for score in _SCORES.values() for case in score.coverages]
    picks = [(truth, evpertur.pick(cov, 0.6)) for truth, cov in cases]
    assert all(got in (truth, "none") for truth, got in picks)


def test_a_single_change_is_absorbed_without_a_person() -> None:
    singles = [name for name in evpertur.OPERATORS if "+" not in name]
    assert all(_SCORES[name].escalated == 0 for name in singles)
