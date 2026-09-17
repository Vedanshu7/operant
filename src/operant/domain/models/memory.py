"""
Cross-run agent memory records, and the keyword matching that recalls them.

Pure: normalisation and similarity are deterministic so recall is
predictable and testable.

Import as:

import operant.domain.models.memory as mdmemory
"""

from __future__ import annotations

import dataclasses
import re
from typing import Final, FrozenSet

import operant.helpers.time as time

# A number or amount not glued to letters (so ids like ``s1`` survive).
_NUMBER_RE: Final = re.compile(r"(?<![A-Za-z])[$€£]?\d[\d,.]*")
_WORD_RE: Final = re.compile(r"[a-z<>]+")
_STOP_WORDS: Final = frozenset(
    {
        "a", "an", "and", "the", "to", "of", "for", "in", "on", "my", "me",
        "i", "is", "it", "then", "tell", "what", "please", "with",
        "from", "this", "that", "at", "be", "by",
    }
)  # fmt: skip


# #############################################################################
# PlanMemory
# #############################################################################


@dataclasses.dataclass(frozen=True)
class PlanMemory:
    """
    A plan that worked for a goal on one app.

    :ivar id: storage id.
    :ivar vendor_id: the app the plan belongs to.
    :ivar goal_key: the normalised goal.
    :ivar goal_text: the goal as written (scrubbed).
    :ivar plan_json: the plan (names only, never values).
    :ivar successes: runs it led to a verified finish.
    :ivar failures: runs that recalled it and still failed.
    :ivar last_used_at: ISO time it last led to a verified finish;
        recalling it does not count, so a plan that keeps failing ages.
    :ivar graph_version: the app graph version it was learned on.
    """

    id: int
    vendor_id: str
    goal_key: str
    goal_text: str
    plan_json: str
    successes: int
    failures: int
    last_used_at: str
    graph_version: int = 0


# #############################################################################
# Lesson
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Lesson:
    """
    A mistake to avoid on one app.

    :ivar id: storage id.
    :ivar vendor_id: the app the lesson belongs to.
    :ivar goal_key: the normalised goal it was learned on.
    :ivar lesson: what went wrong (scrubbed).
    :ivar source: ``verifier`` or ``human``.
    :ivar reinforcements: how often the same lesson recurred.
    :ivar last_used_at: ISO time it last recurred; recalling it does not
        count.
    :ivar subgoal_key: the normalised subgoal it is about (``""`` for a
        person's note).
    :ivar failure_kind: one of ``FAILURE_KINDS`` (``""`` for a person's
        note).
    :ivar graph_version: the app graph version it was learned on.
    """

    id: int
    vendor_id: str
    goal_key: str
    lesson: str
    source: str
    reinforcements: int
    last_used_at: str
    subgoal_key: str = ""
    failure_kind: str = ""
    graph_version: int = 0


def goal_key(goal: str) -> str:
    """
    Normalise a goal for matching.

    Lower-case it, replace numbers and amounts with ``<n>``, and drop
    stop words.

    :param goal: the goal as written.
    :return: the key used to match similar goals.
    """
    lowered = _NUMBER_RE.sub(" <n> ", goal.lower())
    words = [w for w in _WORD_RE.findall(lowered) if w not in _STOP_WORDS]
    key = " ".join(words)
    return key


def similarity(left: str, right: str) -> float:
    """
    Jaccard overlap of two goal keys' word sets.

    :param left: a goal key.
    :param right: another goal key.
    :return: 0.0 (disjoint) to 1.0 (same words).
    """
    a: FrozenSet[str] = frozenset(left.split())
    b: FrozenSet[str] = frozenset(right.split())
    union = a | b
    score = len(a & b) / len(union) if union else 0.0
    return score


def mask_numbers(text: str) -> str:
    """
    Replace numbers and amounts with ``<n>``.

    Stored text then keeps no account numbers, amounts, or ids.

    :param text: text about to be stored.
    :return: the text with every number masked.
    """
    masked = _NUMBER_RE.sub("<n>", text)
    return masked


# #############################################################################
# Lessons and recall scoring
# #############################################################################

# Why a subgoal failed, as a code: the model's own wording is never
# stored, because it can quote whatever text a page put on screen.
FAILURE_KINDS: Final = (
    "not_done",
    "wrong_output",
    "unsafe_step",
    "credential_leak",
    "no_verdict",
)
# Lines in a person's note that read as orders to an assistant, or carry
# a link: a note is replayed into later prompts, so it must stay data.
_INSTRUCTION_RE: Final = re.compile(
    r"https?://|www\.|ignore (all |any )?(previous|prior|above)"
    r"|disregard|system prompt|you are (now )?an?\b"
    r"|\b(assistant|agent|ai|model)\s*[,:]",
    re.IGNORECASE,
)
# Plans and remedies that failed this many more times than they worked
# are no longer offered.
NET_FAILURES: Final = 2
_HALF_LIFE_S: Final = 30 * time.SECONDS_PER_DAY
_HUMAN_BOOST: Final = 2.0
_OLD_VERSION_WEIGHT: Final = 0.5


# #############################################################################
# Rejection
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Rejection:
    """
    A subgoal the verifier panel rejected, as memory keeps it.

    :ivar subgoal: the planner's subgoal description.
    :ivar kind: one of ``FAILURE_KINDS``.
    :ivar count: how often it was rejected in the run.
    """

    subgoal: str
    kind: str
    count: int = 1


def failure_kind(reviewer: str, reason: str) -> str:
    """
    Map a panel rejection to a failure-kind code.

    :param reviewer: the panel member that rejected (``verifier``,
        ``safety``, ``leak``).
    :param reason: its stated reason; only used to tell kinds apart.
    :return: one of ``FAILURE_KINDS``.
    """
    lowered = reason.lower()
    if reviewer == "leak":
        kind = "credential_leak"
    elif reviewer == "safety":
        kind = "unsafe_step"
    elif "no verdict" in lowered:
        kind = "no_verdict"
    elif "output" in lowered or "extract" in lowered:
        kind = "wrong_output"
    else:
        kind = "not_done"
    return kind


def lesson_text(subgoal: str, kind: str, worked: str) -> str:
    """
    Render a lesson in the one shape memory stores.

    :param subgoal: the planner's subgoal description.
    :param kind: a failure-kind code.
    :param worked: what got past it, or ``""`` when nothing did.
    :return: ``On "<subgoal>": <kind>. What worked: <worked>.``
    """
    text = f'On "{subgoal}": {kind}. What worked: {worked or "unresolved"}.'
    return text


def memory_safe(text: str) -> str:
    """
    Drop the lines of a free-text note that read as instructions or links.

    :param text: a person's note, already redacted and scrubbed.
    :return: the remaining lines.
    """
    kept = [
        line for line in text.splitlines() if not _INSTRUCTION_RE.search(line)
    ]
    safe = "\n".join(kept).strip()
    return safe


def recall_score(
    relevance: float,
    *,
    age_s: float,
    reinforcements: int,
    human: bool,
    current_version: bool,
) -> float:
    """
    Score a lesson for recall: relevance, recency, and how often it held.

    :param relevance: goal similarity, 0 to 1.
    :param age_s: seconds since the lesson was last reinforced.
    :param reinforcements: how often it recurred.
    :param human: whether a person wrote it.
    :param current_version: whether it was learned on the app graph
        version in use now.
    :return: a non-negative score; higher recalls first.
    """
    recency = 0.5 ** (max(age_s, 0.0) / _HALF_LIFE_S)
    score = relevance * recency * (1 + reinforcements)
    score *= _HUMAN_BOOST if human else 1.0
    score *= 1.0 if current_version else _OLD_VERSION_WEIGHT
    return score
