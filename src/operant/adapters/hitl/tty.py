"""
Terminal approver and clarifier for interactive CLI runs.

Both take injected ``stdin`` / ``select`` / ``out`` so tests exercise
them without a real terminal. When stdin is not a TTY the clarifier
returns ``""`` (no channel), matching the ``Clarifier`` contract.

Import as:

import operant.adapters.hitl.tty as tty
"""

from __future__ import annotations

import collections.abc
import select
import sys
from typing import Optional, TextIO

import operant.domain.approval as approval
import operant.domain.secrets as odsec

SelectFn = collections.abc.Callable[
    [list[TextIO], list[TextIO], list[TextIO], float],
    tuple[list[TextIO], list[TextIO], list[TextIO]],
]


def render_request(request: approval.ApprovalRequest) -> str:
    """
    Render an approval request as prompt text (values already safe).
    """
    lines = [f"[approval needed: {request.kind}] {request.summary}"]
    if request.step:
        lines.append(f"step: {request.step}")
    lines.extend(
        f"{key}: {value}" for key, value in request.details.items() if value
    )
    text = "\n  ".join(lines)
    return text


# #############################################################################
# TtyApprover
# #############################################################################


class TtyApprover:
    """
    Prompt for y/a/N on the terminal, denying on timeout.
    """

    def __init__(
        self,
        timeout_s: float,
        *,
        stdin: Optional[TextIO] = None,
        select_fn: Optional[SelectFn] = None,
        out: Optional[TextIO] = None,
    ) -> None:
        self.timeout_s = timeout_s
        self._stdin = stdin or sys.stdin
        self._select = select_fn or select.select
        self._out = out or sys.stdout

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """Prompt and map the answer to a decision (timeout = deny)."""
        print(f"\n  {render_request(request)}", file=self._out)
        print(
            "  [y]es once / [a]lways for this process / [N]o  "
            f"(auto-deny in {self.timeout_s:.0f}s) > ",
            end="",
            file=self._out,
            flush=True,
        )
        answer = self._read()
        if answer is None:
            # No answer in time: deny.
            decision = approval.ApprovalDecision(
                approved=False,
                by="timeout",
                note=f"no answer within {self.timeout_s:.0f}s",
            )
        elif answer in {"a", "always"}:
            # Always: remember the grant for this process.
            decision = approval.ApprovalDecision(
                approved=True, remember="process", by="tty"
            )
        elif answer in {"y", "yes"}:
            # Yes: approve just this one time.
            decision = approval.ApprovalDecision(
                approved=True, remember="once", by="tty"
            )
        else:
            # Anything else counts as a denial.
            decision = approval.ApprovalDecision(
                approved=False,
                by="tty",
                note=f"answered {answer!r}" if answer else "no answer",
            )
        return decision

    def _read(self) -> Optional[str]:
        """
        Return the typed line, ``None`` on timeout, ``""`` on error.
        """
        try:
            ready, _, _ = self._select([self._stdin], [], [], self.timeout_s)
            if not ready:
                # Nothing typed before the deadline.
                print(file=self._out)
                line = None
            else:
                # Read the line the operator typed.
                line = self._stdin.readline().strip().lower()
        except (EOFError, KeyboardInterrupt, OSError, ValueError):
            line = ""
        return line


# #############################################################################
# TtyClarifier
# #############################################################################


class TtyClarifier:
    """
    Ask the agent's clarifying question on the terminal.

    Returns ``""`` when stdin is not a TTY, signalling "no channel" so
    the agent resolves the question itself or gives up.
    """

    def __init__(
        self, *, stdin: Optional[TextIO] = None, out: Optional[TextIO] = None
    ) -> None:
        self._stdin = stdin or sys.stdin
        self._out = out or sys.stdout

    def ask(self, question: str, *, run_id: str) -> str:
        """
        Print ``question`` and return the typed answer, else ``""``.
        """
        if not self._stdin.isatty():
            # No terminal: signal "no channel" with an empty answer.
            answer = ""
        else:
            # Prompt on the terminal and read the reply.
            print(
                f"\n  [clarify] {question}\n  > ",
                end="",
                file=self._out,
                flush=True,
            )
            try:
                answer = self._stdin.readline().strip()
            except (EOFError, KeyboardInterrupt, OSError, ValueError):
                answer = ""
        return answer


# #############################################################################
# TtyCredentialRequester
# #############################################################################


class TtyCredentialRequester:
    """
    Ask the operator for a credential the agent needs, on the terminal.

    The operator either types the value or names a source (``env:VAR`` /
    ``keychain:svc/acct``); a source avoids echoing the secret. Returns
    ``None`` (declined) when there is no channel or the operator submits
    a blank line. The value never reaches the model.
    """

    def __init__(
        self, *, stdin: Optional[TextIO] = None, out: Optional[TextIO] = None
    ) -> None:
        self._stdin = stdin or sys.stdin
        self._out = out or sys.stdout

    def request(
        self, name: str, *, run_id: str, reason: str
    ) -> Optional[odsec.CredentialGrant]:
        """
        Prompt for ``name`` and return a typed or sourced grant.
        """
        if not self._stdin.isatty():
            # No terminal: decline the request.
            grant = None
        else:
            # Prompt on the terminal for a value or a source.
            why = f" - {reason}" if reason else ""
            print(
                f"\n  [credential needed: {name}]{why}\n"
                "  enter a value, or a source (env:VAR / keychain:svc/acct), "
                "or blank to skip\n  > ",
                end="",
                file=self._out,
                flush=True,
            )
            try:
                answer = self._stdin.readline().strip()
            except (EOFError, KeyboardInterrupt, OSError, ValueError):
                answer = ""
            if not answer:
                # Blank line: the operator declined.
                grant = None
            elif answer.startswith(("env:", "keychain:")):
                # A source reference avoids echoing the secret.
                grant = odsec.CredentialGrant.sourced(answer)
            else:
                # A literal value typed inline.
                grant = odsec.CredentialGrant.typed(answer)
        return grant
