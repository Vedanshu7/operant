"""
Credential requests over the operator UI: an open request is visible to a
client that missed the live event, and never carries a value.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import operant.domain.secrets as odsec
import operant.server.jobs.hitl as hitl
import operant.server.jobs.pending as pending


def test_an_open_request_is_published_then_cleared() -> None:
    seen: List[Optional[Dict[str, str]]] = []
    answers: List[pending.PendingAnswer[object]] = []

    def register(answer_id: str) -> pending.PendingAnswer[object]:
        answer: pending.PendingAnswer[object] = pending.PendingAnswer(answer_id)
        answer.set(odsec.CredentialGrant.sourced("env:APP_PASSWORD"))
        answers.append(answer)
        return answer

    requester = hitl.UiCredentialRequester(
        "run-1",
        lambda envelope: None,
        register,
        lambda status: None,
        timeout_s=1.0,
        on_pending=seen.append,
    )
    grant = requester.request("password", run_id="run-1", reason="sign in")
    assert grant is not None
    assert len(seen) == 2
    opened, closed = seen[0], seen[1]
    assert opened is not None
    assert opened["name"] == "password"
    assert opened["request_id"].startswith("run-1~cred~")
    assert "APP_PASSWORD" not in str(opened)
    assert closed is None
