"""
Single-agent vs multi-agent scorecard over eval result rows.

Pass rate alone hides most of the trade-off, so the two modes are
compared on several criteria at once:

- Quality: pass rate with a Wilson 95% interval, and pass^k - the chance
  that all k trials of a scenario pass (from tau-bench), which is what a
  user relying on the agent experiences.
- Safety: the safety family's pass rate.
- Robustness: the pass rate of the worst UI skin.
- Cost: dollars per trial and per passed trial, tokens per trial, and
  model calls per trial (executor turns plus every role call).
- Path: steps per task, efficiency against the reference path, in-order.
- Latency: median and 95th-percentile seconds per trial, and the share
  spent waiting on models, when the rows carry ``duration_s``.

``role_table`` splits calls, tokens, cost and model time by agent role,
each role priced at the model it ran on.

Import as:

import tests.evals.compare as evcompar
"""

from __future__ import annotations

import collections
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Row = Dict[str, Any]
Pricer = Callable[[Row], float]
# Prices ``(model, tokens in, tokens out)``.
TokenPricer = Callable[[str, int, int], float]

_MODES = ("single", "multi")


def wilson(passed: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """
    Return the Wilson score interval for a pass rate.

    :param passed: Passing trials.
    :param total: All trials.
    :param z: The normal quantile; 1.96 for 95%.
    :return:``(low, high)`` as fractions; ``(0, 0)`` with no trials.
    """
    if total == 0:
        return 0.0, 0.0
    rate = passed / total
    denominator = 1 + z * z / total
    centre = rate + z * z / (2 * total)
    spread = z * math.sqrt(
        rate * (1 - rate) / total + z * z / (4 * total * total)
    )
    low = (centre - spread) / denominator
    high = (centre + spread) / denominator
    return max(0.0, low), min(1.0, high)


def pass_hat_k(rows: Sequence[Row], k: int) -> Optional[float]:
    """
    Estimate pass^k: the chance that k trials of a scenario all pass.

    Each scenario-skin pair with n >= k trials, c of them passing,
    contributes C(c, k) / C(n, k), the unbiased estimate; the result is
    their mean.

    :param rows: Result rows of one mode.
    :param k: Trials that must all pass.
    :return: The mean estimate, or ``None`` when no pair has k trials.
    """
    groups: Dict[Tuple[str, str], List[bool]] = collections.defaultdict(list)
    for row in rows:
        groups[(row["scenario"], row["skin"])].append(bool(row["passed"]))
    estimates = [
        math.comb(sum(outcomes), k) / math.comb(len(outcomes), k)
        for outcomes in groups.values()
        if len(outcomes) >= k
    ]
    return sum(estimates) / len(estimates) if estimates else None


def percentile(values: Sequence[float], fraction: float) -> float:
    """
    Return the nearest-rank percentile of ``values`` (non-empty).
    """
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def scorecard(rows: Sequence[Row], price: Pricer, *, k: int = 3) -> str:
    """
    Render the single-vs-multi markdown table for one set of rows.

    :param rows: Result rows of both modes.
    :param price: Dollar cost of one row.
    :param k: Trials pass^k requires to all pass.
    :return: A markdown table: one criterion per line, a column per
        mode.
    """
    by_mode = {mode: [r for r in rows if r["mode"] == mode] for mode in _MODES}
    criteria: List[Tuple[str, Callable[[List[Row]], str]]] = [
        ("Pass rate (95% CI)", _pass_rate),
        (f"pass^{k} (all {k} trials pass)", lambda rs: _pass_k(rs, k)),
        ("Safety family pass rate", _safety),
        ("Worst UI skin pass rate", _worst_skin),
        ("Cost per trial", lambda rs: _dollars(rs, price, passed_only=False)),
        (
            "Cost per passed trial",
            lambda rs: _dollars(rs, price, passed_only=True),
        ),
        ("Tokens per trial (in / out)", _tokens),
        ("Model calls per trial", _calls),
        ("Steps per task (reference)", _steps),
        ("Path efficiency / in-order", _path),
        ("Seconds per trial (p50 / p95)", _latency),
        ("Share of time in model calls", _model_share),
    ]
    lines = ["| Criterion | single | multi |", "|---|---|---|"]
    for name, render in criteria:
        cells = [
            render(by_mode[mode]) if by_mode[mode] else "-" for mode in _MODES
        ]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _pass_rate(rows: List[Row]) -> str:
    passed = sum(1 for r in rows if r["passed"])
    low, high = wilson(passed, len(rows))
    return (
        f"{100 * passed / len(rows):.0f}% ({100 * low:.0f}-{100 * high:.0f}%, "
        f"n={len(rows)})"
    )


def _pass_k(rows: List[Row], k: int) -> str:
    estimate = pass_hat_k(rows, k)
    return "-" if estimate is None else f"{100 * estimate:.0f}%"


def _safety(rows: List[Row]) -> str:
    safety = [r for r in rows if r["family"] == "safety"]
    return _pass_rate(safety) if safety else "-"


def _worst_skin(rows: List[Row]) -> str:
    skins: Dict[str, List[bool]] = collections.defaultdict(list)
    for row in rows:
        skins[row["skin"]].append(bool(row["passed"]))
    name, outcomes = min(
        skins.items(), key=lambda item: sum(item[1]) / len(item[1])
    )
    return f"{100 * sum(outcomes) / len(outcomes):.0f}% ({name})"


def _dollars(rows: List[Row], price: Pricer, *, passed_only: bool) -> str:
    total = sum(price(r) for r in rows)
    count = sum(1 for r in rows if r["passed"]) if passed_only else len(rows)
    return f"${total / count:.4f}" if count else "-"


def _tokens(rows: List[Row]) -> str:
    tokens_in = sum(int(r["tokens_in"]) for r in rows) / len(rows)
    tokens_out = sum(int(r["tokens_out"]) for r in rows) / len(rows)
    return f"{tokens_in:,.0f} / {tokens_out:,.0f}"


def _calls(rows: List[Row]) -> str:
    calls = sum(
        int(r["turns"])
        + sum(int(n) for n in (r.get("role_calls") or {}).values())
        for r in rows
    )
    return f"{calls / len(rows):.1f}"


def _steps(rows: List[Row]) -> str:
    scored = [
        r["trajectory"] for r in rows if isinstance(r.get("trajectory"), dict)
    ]
    if not scored:
        return "-"
    steps = sum(float(t["steps"]) for t in scored) / len(scored)
    reference = sum(float(t["reference_steps"]) for t in scored) / len(scored)
    return f"{steps:.1f} ({reference:.1f})"


def _path(rows: List[Row]) -> str:
    scored = [
        r["trajectory"] for r in rows if isinstance(r.get("trajectory"), dict)
    ]
    if not scored:
        return "-"
    efficiency = sum(float(t["efficiency"]) for t in scored) / len(scored)
    in_order = sum(float(t["in_order"]) for t in scored) / len(scored)
    return f"{efficiency:.2f} / {in_order:.2f}"


def _latency(rows: List[Row]) -> str:
    durations = [float(r["duration_s"]) for r in rows if "duration_s" in r]
    if not durations:
        return "not recorded"
    return f"{percentile(durations, 0.5):.1f} / {percentile(durations, 0.95):.1f}"


def _model_share(rows: List[Row]) -> str:
    timed = [
        r for r in rows if r.get("roles") and float(r.get("duration_s", 0)) > 0
    ]
    if not timed:
        return "not recorded"
    model_s = sum(
        float(usage["seconds"]) for r in timed for usage in r["roles"].values()
    )
    total_s = sum(float(r["duration_s"]) for r in timed)
    return f"{100 * model_s / total_s:.0f}%"


def role_table(rows: Sequence[Row], price: TokenPricer) -> str:
    """
    Render calls, tokens, cost and model time per agent role and mode.

    :param rows: Result rows that carry per-role ``roles`` usage.
    :param price: Dollar cost of a model's tokens.
    :return: A markdown table, averaged per trial of each mode.
    """
    lines = [
        "| Mode | Role | Model | Calls / trial | Tokens / trial (in / out) "
        "| Cost / trial | Model seconds / trial |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode in _MODES:
        trials = [r for r in rows if r["mode"] == mode and r.get("roles")]
        totals: Dict[Tuple[str, str], List[float]] = collections.defaultdict(
            lambda: [0.0, 0.0, 0.0, 0.0, 0.0]
        )
        for row in trials:
            for role, usage in row["roles"].items():
                total = totals[(role, usage["model"])]
                total[0] += usage["calls"]
                total[1] += usage["tokens_in"]
                total[2] += usage["tokens_out"]
                total[3] += price(
                    usage["model"], usage["tokens_in"], usage["tokens_out"]
                )
                total[4] += usage["seconds"]
        for (role, model), total in sorted(totals.items()):
            calls, tokens_in, tokens_out, cost, seconds = (
                value / len(trials) for value in total
            )
            lines.append(
                f"| {mode} | {role} | {model or '-'} | {calls:.1f} | "
                f"{tokens_in:,.0f} / {tokens_out:,.0f} | ${cost:.4f} | "
                f"{seconds:.1f} |"
            )
    if len(lines) == 2:
        lines.append(
            "| - | per-role usage not recorded in these rows | | | | | |"
        )
    return "\n".join(lines)
