"""
Drive a live Operant run through the operator API, as the web UI would.

App-agnostic: the profile, tenant, goal and agent mode come from the
command line; credential requests are answered with the locator the
profile's tenant already binds for that name (``env:`` / ``keychain:``),
never with a typed value. Approvals are granted automatically only when
the tenant's base URL is local (a sandbox on this machine); anything
else is refused and the run stops for a person. Each finished run is
appended to ``state/live/<session>.jsonl``.

Run: ``uv run python scripts/live_demo.py --base
http://127.0.0.1:7080
     --token <token> --profile <id> --tenant <tenant> --goal "<goal>"
[--agents multi] [--replay] [--clarify "url=
http://..."]``
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
from typing import Any, Dict, List

import httpx

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Mirrors operant.domain.models.runs.TERMINAL_STATUSES.
_TERMINAL = frozenset(
    {"succeeded", "business_outcome", "escalated", "failed", "cancelled"}
)


def _slug(text: str) -> str:
    """
    Make a capability id from a goal.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]
    return slug or "live-run"


# #############################################################################
# Operator
# #############################################################################


class Operator:
    """
    Answer a run's questions over the API on the operator's behalf.
    """

    def __init__(
        self,
        client: httpx.Client,
        profile: Dict[str, Any],
        tenant: str,
        clarify: Dict[str, str],
    ) -> None:
        self._client = client
        binding = profile.get("tenants", {}).get(tenant, {})
        self._refs: Dict[str, str] = dict(binding.get("secret_refs", {}))
        host = urllib.parse.urlparse(str(binding.get("base_url", ""))).hostname
        self._local = host in _LOCAL_HOSTS
        self._clarify = clarify
        self.notes: List[str] = []

    def credential(self, data: Dict[str, Any]) -> None:
        """
        Answer a credential request with the profile's bound locator.
        """
        name = str(data.get("name", ""))
        locator = self._refs.get(name) or next(
            (v for k, v in self._refs.items() if k.lower() == name.lower()), None
        )
        if locator is None:
            # No binding for this name: a person must decide.
            self.notes.append(f"no secret ref for credential {name!r}")
            return
        self._client.post(
            f"/credentials/{data['request_id']}", json={"locator": locator}
        ).raise_for_status()
        self.notes.append(
            f"credential {name} -> {locator.split(':', 1)[0]}: source"
        )

    def approval(self, data: Dict[str, Any]) -> None:
        """
        Approve inside a local sandbox only; refuse everywhere else.
        """
        record = data.get("approval") or {}
        approved = self._local
        self._client.post(
            f"/approvals/{record['id']}",
            json={
                "approved": approved,
                "note": "live demo: local sandbox" if approved else "not local",
            },
        ).raise_for_status()
        self.notes.append(
            f"approval {'granted' if approved else 'refused'}: {record.get('summary', '')}"
        )

    def clarification(self, data: Dict[str, Any]) -> None:
        """
        Answer a clarifying question from the --clarify map.
        """
        record = data.get("clarification") or {}
        question = str(record.get("question", ""))
        answer = next(
            (
                v
                for k, v in self._clarify.items()
                if k.lower() in question.lower()
            ),
            "",
        )
        self._client.post(
            f"/clarifications/{record['id']}", json={"answer": answer}
        ).raise_for_status()
        self.notes.append(f"clarify {question!r} -> {answer or '(no answer)'}")


def _events(client: httpx.Client, run_id: str, timeout_s: float) -> Any:
    """
    Yield the run's SSE envelopes until it reaches a terminal status.
    """
    deadline = time.monotonic() + timeout_s
    with client.stream(
        "GET",
        f"/runs/{run_id}/events",
        timeout=httpx.Timeout(timeout_s, read=60.0),
    ) as stream:
        for line in stream.iter_lines():
            if time.monotonic() > deadline:
                return
            if line.startswith("data:"):
                envelope = json.loads(line[5:].strip())
                yield envelope
                if envelope.get("run_status") in _TERMINAL:
                    return


def run(
    client: httpx.Client,
    body: Dict[str, Any],
    operator: Operator,
    *,
    kind: str,
    timeout_s: float,
) -> Dict[str, Any]:
    """
    Start a discovery or replay and operate it to completion.

    :return: The final run record plus what the operator did.
    """
    started = client.post(f"/runs/{kind}", json=body)
    started.raise_for_status()
    run_id = started.json()["id"]
    handlers = {
        "credential_requested": operator.credential,
        "approval_requested": operator.approval,
        "clarify": operator.clarification,
    }
    for envelope in _events(client, run_id, timeout_s):
        handler = handlers.get(envelope.get("type", ""))
        if handler is not None:
            handler(envelope.get("data") or {})
    record = client.get(f"/runs/{run_id}").json()
    if record.get("status") not in _TERMINAL:
        # Out of time: stop it so it does not hold the screen.
        client.post(f"/runs/{run_id}/cancel")
        record = client.get(f"/runs/{run_id}").json()
    record["operator_notes"] = list(operator.notes)
    operator.notes.clear()
    return record


def _reason(record: Dict[str, Any]) -> str:
    """
    Say why a run ended: its error, or a replay's failure class.
    """
    failure = (record.get("result") or {}).get("failure") or {}
    reason = (
        record.get("error")
        or (
            f"{failure.get('failure_class')}: expected "
            f"{failure.get('expected')}"
            if failure
            else ""
        )
        or "ok"
    )
    return str(reason)


def main() -> int:
    """
    Run one discovery (and optionally its replay) and report the result.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base", default="http://127.0.0.1:7080")
    parser.add_argument("--token", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--capability", default="")
    parser.add_argument("--agents", choices=("single", "multi"), default="single")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--clarify", action="append", default=[])
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="NAME=VALUE typed input for the discovery (repeatable)",
    )
    parser.add_argument(
        "--replay-input",
        action="append",
        default=[],
        help="NAME=VALUE input for the replay (repeatable)",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    clarify = dict(item.split("=", 1) for item in args.clarify)
    client = httpx.Client(
        base_url=f"{args.base}/api/v1",
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=30.0,
    )
    profile = client.get(f"/profiles/{args.profile}").json()
    operator = Operator(client, profile, args.tenant, clarify)
    capability = args.capability or _slug(args.goal)
    results = [
        run(
            client,
            {
                "goal": args.goal,
                "capability_id": capability,
                "profile_id": args.profile,
                "tenant": args.tenant,
                "agents": args.agents,
                "inputs": dict(item.split("=", 1) for item in args.input),
            },
            operator,
            kind="discovery",
            timeout_s=args.timeout,
        )
    ]
    if args.replay and results[0].get("status") == "succeeded":
        results.append(
            run(
                client,
                {
                    "capability_id": capability,
                    "tenant": args.tenant,
                    "inputs": dict(
                        item.split("=", 1) for item in args.replay_input
                    ),
                },
                operator,
                kind="replay",
                timeout_s=args.timeout,
            )
        )
    out = _ROOT / "state" / "live" / f"{time.strftime('%Y%m%d')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        for record in results:
            fh.write(json.dumps({"agents": args.agents, **record}) + "\n")
    for record in results:
        print(
            f"{record.get('kind')}: {record.get('status')} "
            f"({_reason(record)}) evidence={record.get('evidence_dir')}"
        )
        for note in record.get("operator_notes", []):
            print(f"  - {note}")
    ok = all(r.get("status") == "succeeded" for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
