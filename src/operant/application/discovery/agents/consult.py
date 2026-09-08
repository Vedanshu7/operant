"""
One-shot calls to a non-executor role: one prompt in, one tool call out.

Every call is traced under the run's trace with the role as its agent,
and the text sent was already redacted and scrubbed by the caller.

Import as:

import operant.application.discovery.agents.consult as daconsul
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

import operant.application.discovery.agents.prompts as daprompt
import operant.application.discovery.observe as dsobserv
import operant.domain.errors as errors
import operant.domain.models.llm as llm

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop


def system_prompt(session: loop.DiscoverySession, role: str) -> str:
    """
    Return the role's system prompt, honoring a per-run override.

    :param session: The discovery session.
    :param role: The role name, e.g. ``planner``.
    :return: The prompt text.
    """
    text = session.cfg.prompt_overrides.get(role, daprompt.PROMPTS[role])
    return text


def ask(
    session: loop.DiscoverySession,
    role: str,
    text: str,
    *,
    turn: int,
    traced_text: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Ask ``role`` once and return the arguments of its tool call.

    :param session: The discovery session (for the model and tracing).
    :param role: Which role answers.
    :param text: The user message.
    :param turn: The executor turn this call belongs to.
    :param traced_text: What to trace instead of ``text``, when ``text``
        itself is not safe to leave the process (the extract helper
        reads the raw screen, like the executor).
    :return: The parsed tool arguments, or ``None`` when the model
        failed or answered without the expected tool.
    """
    tools = daprompt.TOOLS[role]
    messages = (
        llm.ChatMessage(role="system", content=system_prompt(session, role)),
        llm.ChatMessage(role="user", content=text),
    )
    client = session.deps.role_llms.get(role, session.deps.llm)
    traced = dsobserv.traced_prompt(
        (
            messages[0],
            llm.ChatMessage(role="user", content=traced_text or text),
        ),
        redact=lambda s: s,
        scrubber=None,
    )
    answer: Optional[Dict[str, Any]] = None
    for attempt in range(max(1, session.deps.llm_retries)):
        try:
            with session.deps.tracer.generation(
                session.trace_context(role, turn),
                model=session.deps.role_models.get(role, session.deps.model_name),
                prompt=traced,
            ) as generation:
                reply = client.complete(messages, tools=tools)
                generation.finish(reply, output=dsobserv.turn_output(reply))
            wanted = {tool.name for tool in tools}
            call = next((c for c in reply.tool_calls if c.name in wanted), None)
            answer = _parse(call.arguments) if call is not None else None
            break
        # A failed role call degrades the run (fallback plan, no verdict);
        # it never crashes it. Retryable errors (rate limits) back off.
        except errors.LlmError as err:
            if not err.retryable:
                break
            time.sleep(session.deps.retry_base_delay_s * (attempt + 1))
    return answer


def _parse(arguments: str) -> Optional[Dict[str, Any]]:
    """
    Parse tool arguments; ``None`` when they are not a JSON object.
    """
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        parsed = None
    result = parsed if isinstance(parsed, dict) else None
    return result
