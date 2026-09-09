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


def _cost(rows: List[Dict[str, Any]]) -> float:
    """
    Price a set's tokens with litellm's model map.
    """
    prompt = sum(int(r["tokens_in"]) for r in rows)
    completion = sum(int(r["tokens_out"]) for r in rows)
    cost = sum(
        litellm.cost_per_token(
            model=_MODEL, prompt_tokens=prompt, completion_tokens=completion
        )
    )
    return cost


def report(sets: List[Tuple[str, List[Dict[str, Any]]]]) -> str:
    """
    Build the markdown report for the given labelled sets.

    :param sets:``(label, rows)`` in column order.
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
    return "\n".join(lines)


def main() -> int:
    """
    Print the report for the sets on the command line.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--set", action="append", required=True, dest="sets")
    args = parser.parse_args()
    print(report([_load(spec) for spec in args.sets]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
