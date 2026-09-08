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

    :ivar id: Storage id.
    :ivar vendor_id: The app the plan belongs to.
    :ivar goal_key: The normalised goal.
    :ivar goal_text: The goal as written (scrubbed).
    :ivar plan_json: The plan (names only, never values).
    :ivar successes: Runs it led to a verified finish.
    :ivar failures: Runs that used it and still escalated.
    :ivar last_used_at: ISO time it was last recorded or recalled.
    """

    id: int
    vendor_id: str
    goal_key: str
    goal_text: str
    plan_json: str
    successes: int
    failures: int
    last_used_at: str


# #############################################################################
# Lesson
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Lesson:
    """
    A mistake to avoid on one app.

    :ivar id: Storage id.
    :ivar vendor_id: The app the lesson belongs to.
    :ivar goal_key: The normalised goal it was learned on.
    :ivar lesson: What went wrong (scrubbed).
    :ivar source:``verifier`` or ``human``.
    :ivar reinforcements: How often the same lesson recurred.
    :ivar last_used_at: ISO time it was last recorded or recalled.
    """

    id: int
    vendor_id: str
    goal_key: str
    lesson: str
    source: str
    reinforcements: int
    last_used_at: str


def goal_key(goal: str) -> str:
    """
    Normalise a goal: lower case, numbers and amounts as ``<n>``, stop words
    dropped.

    :param goal: The goal as written.
    :return: The key used to match similar goals.
    """
    lowered = _NUMBER_RE.sub(" <n> ", goal.lower())
    words = [w for w in _WORD_RE.findall(lowered) if w not in _STOP_WORDS]
    key = " ".join(words)
    return key


def similarity(left: str, right: str) -> float:
    """
    Jaccard overlap of two goal keys' word sets.

    :param left: A goal key.
    :param right: Another goal key.
    :return: 0.0 (disjoint) to 1.0 (same words).
    """
    a: FrozenSet[str] = frozenset(left.split())
    b: FrozenSet[str] = frozenset(right.split())
    union = a | b
    score = len(a & b) / len(union) if union else 0.0
    return score


def mask_numbers(text: str) -> str:
    """
    Replace numbers and amounts with ``<n>`` so stored text keeps no account
    numbers, amounts, or ids.

    :param text: Text about to be stored.
    :return: The text with every number masked.
    """
    masked = _NUMBER_RE.sub("<n>", text)
    return masked
