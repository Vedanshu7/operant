"""
Optimize the discovery prompts with GEPA over the eval scenarios.

Each rollout runs one eval scenario against the configured discovery
model; GEPA's reflection model reads the check failures and proposes
better prompts. The best prompts, a diff against the source, and the
per-candidate validation scores are written to ``state/gepa/<ts>/``.
Source files are never edited: review ``diff.patch``, apply it by hand,
then re-run the evals.

Needs the ``optimize`` extra and a model key. Opt-in; never run in CI.

Run: ``uv run python scripts/optimize_prompt.py [--mode single|multi]
[--budget 150] [--reflection-model anthropic/claude-opus-5-5]``
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import pathlib
import random
import sys
import time
from typing import Dict, List, Tuple

import gepa

import operant.adapters.llm.litellm_client as litecli
import operant.adapters.observability.factory as aofactor
import operant.adapters.privacy.factory as apfactor
import operant.adapters.secrets.env as env
import operant.helpers.logging as logging
import operant.infra.settings as settings
import tests.evals.gepa_adapter as gepaadap
import tests.evals.harness as harness

_LOG = logging.get_logger(__name__)
_ROOT = pathlib.Path(__file__).resolve().parents[1]
# Held out of training so the prompt is not tuned to ParaBank's wording.
_VAL_ONLY_SKIN = "bank"
_FAMILIES = ("auth", "grounding", "io", "safety", "multistep")


def _parse() -> argparse.Namespace:
    """
    Parse command-line options; defaults come from ``OPERANT_GEPA__*``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--mode",
        choices=("single", "multi"),
        default=os.environ.get("OPERANT_GEPA__MODE", "single"),
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=int(os.environ.get("OPERANT_GEPA__BUDGET", "150")),
        help="maximum scenario rollouts (metric calls)",
    )
    parser.add_argument(
        "--reflection-model",
        default=os.environ.get(
            "OPERANT_GEPA__REFLECTION_MODEL", "anthropic/claude-opus-5-5"
        ),
    )
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def _split(
    scenarios: List[harness.Scenario], seed: int
) -> Tuple[List[harness.Scenario], List[harness.Scenario]]:
    """
    Split into train and validation with a fixed seed; the ParaBank-like skin
    is validation only.
    """
    held = [s for s in scenarios if s.skin.name == _VAL_ONLY_SKIN]
    rest = [s for s in scenarios if s.skin.name != _VAL_ONLY_SKIN]
    random.Random(seed).shuffle(rest)
    cut = max(1, int(len(rest) * 0.7))
    train, val = rest[:cut], held + rest[cut:]
    return train, val


def _diff(seed: Dict[str, str], best: Dict[str, str]) -> str:
    """
    Render a unified diff per changed component.
    """
    chunks: List[str] = []
    for name, before in seed.items():
        after = best.get(name, before)
        if after != before:
            chunks.extend(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{name}",
                    tofile=f"b/{name}",
                )
            )
    diff = "".join(chunks) or "# no change: the seed prompts scored best\n"
    return diff


def main() -> int:
    """
    Run GEPA and write its results; return the process exit code.
    """
    args = _parse()
    loaded = settings.OperantSettings.load(root=_ROOT)
    if not loaded.discovery.model:
        _LOG.error("set OPERANT_DISCOVERY__MODEL (and its API key) first")
        return 1
    out = _ROOT / "state" / "gepa" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    clients = litecli.build_clients(loaded.discovery)
    eval_env = harness.EvalEnv(
        llm=clients.executor,
        role_llms=dict(clients.roles),
        secret_store=env.EnvSecretStore({}),
        tracer=aofactor.tracer(loaded.observability),
        scrubber=apfactor.scrubber(loaded.privacy),
    )
    train, val = _split(gepaadap.instances(_FAMILIES), args.seed)
    seed = gepaadap.seed_candidate(args.mode)
    _LOG.info(
        "GEPA: %s mode, %d train / %d val, budget %d, reflection %s",
        args.mode,
        len(train),
        len(val),
        args.budget,
        args.reflection_model,
    )
    result = gepa.optimize(
        seed_candidate=seed,
        trainset=train,
        valset=val,
        adapter=gepaadap.OperantAdapter(
            eval_env, mode=args.mode, work_dir=out / "rollouts"
        ),
        reflection_lm=args.reflection_model,
        max_metric_calls=args.budget,
        run_dir=str(out / "gepa"),
        seed=args.seed,
    )
    if eval_env.tracer is not None:
        eval_env.tracer.flush()
    best = dict(result.best_candidate)
    (out / "best_prompts.json").write_text(json.dumps(best, indent=2))
    (out / "diff.patch").write_text(_diff(seed, best))
    (out / "pareto.json").write_text(
        json.dumps(
            {
                "best_idx": result.best_idx,
                "val_aggregate_scores": list(result.val_aggregate_scores),
                "seed_val_score": result.val_aggregate_scores[0],
                "best_val_score": result.val_aggregate_scores[result.best_idx],
                "total_metric_calls": result.total_metric_calls,
            },
            indent=2,
        )
    )
    _LOG.info(
        "wrote %s (best val score %.3f, seed %.3f)",
        out,
        result.val_aggregate_scores[result.best_idx],
        result.val_aggregate_scores[0],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
