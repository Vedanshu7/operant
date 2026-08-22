import io

import operant.adapters.hitl.tty as tty
import operant.domain.approval as approval


def _request() -> approval.ApprovalRequest:
    return approval.ApprovalRequest(
        kind="sensitive_fill",
        summary='fill "Password" with [credential, 7 chars]',
        details={"field": "Password", "data_class": "credential"},
        action_kind="fill",
    )


def _ready(readers, writers, errs, timeout):
    return readers, [], []


def _empty(readers, writers, errs, timeout):
    return [], [], []


def test_tty_approver_maps_answers_and_shows_safe_details() -> None:
    out = io.StringIO()
    always = tty.TtyApprover(
        5, stdin=io.StringIO("a\n"), select_fn=_ready, out=out
    ).ask(_request())
    assert always.approved and always.remember == "process" and always.by == "tty"
    assert "Password" in out.getvalue()
    once = tty.TtyApprover(
        5, stdin=io.StringIO("y\n"), select_fn=_ready, out=io.StringIO()
    ).ask(_request())
    assert once.approved and once.remember == "once"
    no = tty.TtyApprover(
        5, stdin=io.StringIO("n\n"), select_fn=_ready, out=io.StringIO()
    ).ask(_request())
    assert not no.approved and no.by == "tty"
    blank = tty.TtyApprover(
        5, stdin=io.StringIO("\n"), select_fn=_ready, out=io.StringIO()
    ).ask(_request())
    assert not blank.approved


def test_tty_approver_times_out() -> None:
    timed_out = tty.TtyApprover(
        0.01, stdin=io.StringIO(""), select_fn=_empty, out=io.StringIO()
    ).ask(_request())
    assert not timed_out.approved and timed_out.by == "timeout"


# #############################################################################
# _Tty
# #############################################################################


class _Tty(io.StringIO):

    def isatty(self) -> bool:
        return True


def test_tty_clarifier_reads_when_interactive_and_skips_otherwise() -> None:
    answered = tty.TtyClarifier(stdin=_Tty("12456\n"), out=io.StringIO()).ask(
        "which account?", run_id="r"
    )
    assert answered == "12456"
    non_tty = tty.TtyClarifier(
        stdin=io.StringIO("ignored\n"), out=io.StringIO()
    ).ask("which account?", run_id="r")
    assert non_tty == ""
