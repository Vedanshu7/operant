#!/usr/bin/env python
"""
Drive a live Operant run through the operator API, as the web UI would.

App-agnostic: the profile, tenant, goal and agent mode come from the
command line; credential requests are answered with the locator the
profile's tenant already binds for that name (``env:`` / ``keychain:``),
never with a typed value. Approvals are granted automatically only when
the tenant's base URL is local (a sandbox on this machine); anything
else is refused and the run stops for a person. Each finished run is
appended to ``state/live/<session>.jsonl``.

For a recorded demo, ``--ui-script <file>`` writes a page script that
types the goal into the desktop app's form and starts it (run it with
``OPERANT_DESKTOP_SCRIPT=<file>``); ``--attach`` then operates the run
the UI started instead of starting one over the API.

Run ``uv run python scripts/live_demo.py --help`` for the options:
``--base`` and ``--token`` reach the server, ``--profile``, ``--tenant``
and ``--goal`` describe the run, and ``--agents``, ``--replay`` and
``--clarify`` are optional.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set

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
        # Pending items can arrive twice (run detail and stream).
        self._answered: Set[str] = set()

    def first_time(self, item_id: str) -> bool:
        """
        Whether ``item_id`` has not been answered yet (and mark it).
        """
        fresh = item_id not in self._answered
        self._answered.add(item_id)
        return fresh

    def credential(self, data: Dict[str, Any]) -> None:
        """
        Answer a credential request with the profile's bound locator.
        """
        name = str(data.get("name", ""))
        if not self.first_time(str(data.get("request_id"))):
            return
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
        if not self.first_time(str(record.get("id"))):
            return
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
        if not self.first_time(str(record.get("id"))):
            return
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

    A quiet stretch can outlast one connection, so the stream reconnects
    from the last event seen until the run ends or ``timeout_s`` passes.
    """
    deadline = time.monotonic() + timeout_s
    seen = -1
    while time.monotonic() < deadline:
        # Live-only events sent while disconnected are lost; the run detail
        # still lists what is waiting for an answer.
        yield from _pending(client.get(f"/runs/{run_id}").json())
        try:
            with client.stream(
                "GET",
                f"/runs/{run_id}/events",
                params={"after": seen},
                timeout=httpx.Timeout(30.0, read=90.0),
            ) as stream:
                for line in stream.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    envelope = json.loads(line[5:].strip())
                    seen = max(seen, int(envelope.get("seq", seen)))
                    yield envelope
                    if envelope.get("run_status") in _TERMINAL:
                        return
        except httpx.TransportError:
            # Dropped or idle connection: reconnect from the last event.
            pass
        status = client.get(f"/runs/{run_id}").json().get("status")
        if status in _TERMINAL:
            return


def _pending(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Turn the run detail's open questions into stream-shaped envelopes.
    """
    found: List[Dict[str, Any]] = []
    if detail.get("pending_credential"):
        found.append(
            {"type": "credential_requested", "data": detail["pending_credential"]}
        )
    if detail.get("pending_approval"):
        found.append(
            {
                "type": "approval_requested",
                "data": {"approval": detail["pending_approval"]},
            }
        )
    if detail.get("pending_clarification"):
        found.append(
            {
                "type": "clarify",
                "data": {"clarification": detail["pending_clarification"]},
            }
        )
    return found


def _latest_run(client: httpx.Client) -> str:
    """
    Return the newest run's id, or ``""`` when there is none.
    """
    items = client.get("/runs", params={"limit": 1}).json().get("items", [])
    return str(items[0]["id"]) if items else ""


def _attached(client: httpx.Client, before: str, timeout_s: float) -> str:
    """
    Wait for a run newer than ``before`` (one the UI started).
    """
    deadline = time.monotonic() + timeout_s
    run_id = _latest_run(client)
    while run_id == before and time.monotonic() < deadline:
        time.sleep(0.5)
        run_id = _latest_run(client)
    if run_id == before:
        raise SystemExit("no run was started from the UI in time")
    return run_id


def run(
    client: httpx.Client,
    body: Dict[str, Any],
    operator: Operator,
    *,
    kind: str,
    timeout_s: float,
    attach_after: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Start a discovery or replay and operate it to completion.

    :param attach_after: Operate the first run newer than this id
        instead of starting one (the UI starts it).
    :return: The final run record plus what the operator did.
    """
    if attach_after is not None:
        run_id = _attached(client, attach_after, timeout_s)
    else:
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


_UI_SCRIPT = """
(async () => {
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  const until = async (find) => {
    for (let i = 0; i < 100 && !find(); i++) await wait(100);
    return find();
  };
  // React tracks a control's value itself: set it the native way, then
  // fire the event React listens for.
  const set = (el, value) => {
    const proto = Object.getPrototypeOf(el);
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input",
      { bubbles: true }));
  };
  const byId = (id) => until(() => document.getElementById(id));
  const typeSlowly = async (el, text) => {
    el.focus();
    for (let i = 1; i <= text.length; i++) { set(el, text.slice(0, i)); await wait(45); }
  };
  const form = __FORM__;
  await typeSlowly(await byId("goal"), form.goal);
  await wait(400);
  const profile = await byId("profile");
  await until(() => [...profile.options].some((o) => o.value === form.profile));
  set(profile, form.profile);
  await wait(400);
  const tenant = await byId("tenant");
  await until(() => [...tenant.options].some((o) => o.value === form.tenant));
  set(tenant, form.tenant);
  await wait(300);
  const capability = await byId("capability_id");
  set(capability, form.capability);
  set(await byId("agents"), form.agents);
  const buttons = () => [...document.querySelectorAll("button")];
  for (const [index, [key, value]] of form.inputs.entries()) {
    buttons().find((b) => b.textContent.trim() === "+ Add input").click();
    const n = index + 1;
    await typeSlowly(await until(() =>
      document.querySelector(`[aria-label="Input ${n} key"]`)), key);
    await typeSlowly(await until(() =>
      document.querySelector(`[aria-label="Input ${n} value"]`)), value);
  }
  await wait(900);
  buttons().find((b) => b.textContent.trim() === "Start discovery").click();
})();
"""


def _ui_script(args: argparse.Namespace, capability: str) -> str:
    """
    Build the page script that fills and submits the discovery form.
    """
    form = {
        "goal": args.goal,
        "profile": args.profile,
        "tenant": args.tenant,
        "capability": capability,
        "agents": args.agents,
        "inputs": [item.split("=", 1) for item in args.input],
    }
    return _UI_SCRIPT.replace("__FORM__", json.dumps(form))


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
    parser.add_argument(
        "--ui-script",
        type=pathlib.Path,
        help="write the desktop page script for this goal and exit",
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        help="operate the discovery the UI starts instead of starting one",
    )
    args = parser.parse_args()
    capability = args.capability or _slug(args.goal)
    if args.ui_script is not None:
        args.ui_script.write_text(_ui_script(args, capability))
        return 0
    clarify = dict(item.split("=", 1) for item in args.clarify)
    client = httpx.Client(
        base_url=f"{args.base}/api/v1",
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=30.0,
    )
    profile = client.get(f"/profiles/{args.profile}").json()
    operator = Operator(client, profile, args.tenant, clarify)
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
            attach_after=_latest_run(client) if args.attach else None,
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
