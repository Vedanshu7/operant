#!/usr/bin/env python
"""
Turn eval result files into the README's markdown tables.

Each ``--set LABEL=FILE[,FILE...]`` is one column group (e.g. ``before``,
``after``, ``gepa``); several files in a set are concatenated (a run that
was resumed). The report has: pass rate per family and agent mode per
set, trajectory efficiency, verifier error rates (multi-agent), and the
API cost of each set from its token counts.

Run: ``uv run python scripts/eval_report.py --set before=a.jsonl,b.jsonl
--set after=c.jsonl``
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any, Dict, List, Tuple

import litellm

import tests.evals.compare as evcompar
import tests.evals.trajectory as trajecto

_MODEL = "anthropic/claude-haiku-4-5"
_FAMILIES = ("auth", "grounding", "io", "safety", "multistep", "context")


def _load(spec: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Parse ``LABEL=FILE[,FILE...]`` and load its rows.
    """
    label, _, files = spec.partition("=")
    rows = [
        json.loads(line)
        for path in files.split(",")
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return label, rows


def _rate(rows: List[Dict[str, Any]]) -> str:
    """
    Render passed/total and the percentage.
    """
    if not rows:
        return "-"
    passed = sum(1 for r in rows if r["passed"])
    return f"{passed}/{len(rows)} ({100 * passed / len(rows):.0f}%)"


def _price(model: str, tokens_in: int, tokens_out: int) -> float:
    """
    Price tokens of one model with litellm's model map.

    Rows written before per-role usage was recorded name no model; they
    were all Haiku.
    """
    cost = sum(
        litellm.cost_per_token(
            model=model or _MODEL,
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
        )
    )
    return cost


def _row_cost(row: Dict[str, Any]) -> float:
    """
    Price one trial, each role at its own model when recorded.
    """
    roles = row.get("roles")
    if roles:
        # Per-role usage: each role is priced at the model it ran on.
        cost = sum(
            _price(usage["model"], usage["tokens_in"], usage["tokens_out"])
            for usage in roles.values()
        )
    else:
        # Older rows: one model for every token.
        cost = _price("", int(row["tokens_in"]), int(row["tokens_out"]))
    return cost


def _cost(rows: List[Dict[str, Any]]) -> float:
    """
    Price a set's tokens.
    """
    cost = sum(_row_cost(row) for row in rows)
    return cost


def report(sets: List[Tuple[str, List[Dict[str, Any]]]]) -> str:
    """
    Build the markdown report for the given labelled sets.

    :param sets: ``(label, rows)`` in column order.
    :return: Markdown text.
    """
    labels = [label for label, _ in sets]
    header = "| Family | " + " | ".join(
        f"{label} single | {label} multi" for label in labels
    )
    lines = [
        header + " |",
        "|---|" + "---|" * (2 * len(labels)),
    ]
    by: Dict[str, Dict[Tuple[str, str], List[Dict[str, Any]]]] = {}
    for label, rows in sets:
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = (
            collections.defaultdict(list)
        )
        for row in rows:
            grouped[(row["family"], row["mode"])].append(row)
        by[label] = grouped
    for family in _FAMILIES:
        cells = [
            _rate(by[label].get((family, mode), []))
            for label in labels
            for mode in ("single", "multi")
        ]
        lines.append(f"| {family} | " + " | ".join(cells) + " |")
    totals = [
        _rate([r for r in rows if r["mode"] == mode])
        for _, rows in sets
        for mode in ("single", "multi")
    ]
    lines.append("| **all** | " + " | ".join(f"**{t}**" for t in totals) + " |")
    lines += [
        "",
        "| Set | Trials | Cost | Trajectory efficiency | In-order | Verifier false accepts | Verifier false rejects |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, rows in sets:
        scored = [r for r in rows if r.get("trajectory")]
        summary = trajecto.summarize(scored) if scored else {}
        multi = [r for r in rows if r["mode"] == "multi" and r.get("verifier")]
        verdicts = trajecto.summarize(multi) if multi else {}
        efficiency = f"{summary['efficiency']:.2f}" if summary else "-"
        in_order = f"{summary['in_order']:.2f}" if summary else "-"
        accepts = (
            f"{verdicts['false_accept']:.0f} of "
            f"{verdicts['true_accept'] + verdicts['false_accept']:.0f}"
            if verdicts
            else "-"
        )
        rejects = (
            f"{verdicts['false_reject']:.0f} of "
            f"{verdicts['true_reject'] + verdicts['false_reject']:.0f}"
            if verdicts
            else "-"
        )
        lines.append(
            f"| {label} | {len(rows)} | ${_cost(rows):.2f} | {efficiency} | "
            f"{in_order} | {accepts} | {rejects} |"
        )
    for label, rows in sets:
        lines += [
            "",
            f"Single vs multi agent ({label}):",
            "",
            evcompar.scorecard(rows, _row_cost),
            "",
            f"Cost by agent role ({label}):",
            "",
            evcompar.role_table(rows, _price),
        ]
    return "\n".join(lines)


def main() -> int:
    """
    Print the report for the sets on the command line.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--set", action="append", default=[], dest="sets")
    parser.add_argument(
        "--live",
        action="append",
        default=[],
        help="Live run records (state/live/*.jsonl) for latency/throughput.",
    )
    args = parser.parse_args()
    if not args.sets and not args.live:
        parser.error("give at least one --set or --live")
    if args.sets:
        print(report([_load(spec) for spec in args.sets]))
    if args.live:
        records = [
            json.loads(line)
            for path in args.live
            for line in pathlib.Path(path)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        print("\nLive runs: latency and throughput\n")
        print(evcompar.live_table(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
