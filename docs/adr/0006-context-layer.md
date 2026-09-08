# 6. Context layer for model calls

Status: Accepted (implemented)

## Context

Every discovery turn appends a screen digest and a base64 screenshot to the
chat history, and the whole history is sent on every call. Nothing is ever
dropped.

- By turn N the model receives N screenshots.
- Token use grows with every turn.
- There is no token count and no per-model limit.
- The only guard is `max_turns` (default 40).

The digest itself is bounded (60 controls, 2,500 characters of text), but
the history is not.

## Decision

Add a `ContextBuilder` that builds the messages for each call. The stored
history stays complete as the record. Only what is sent changes.

- Images: only the latest screenshot is sent. Older ones become a short
  "screenshot omitted" note.
- Digests: the last few turns keep the full digest. Older turns keep only
  the window title and the action result.
- Subgoals: in multi mode, a passed subgoal becomes one summary line
  (ADR 5).
- Budget: count tokens with litellm. The limit is the model's input limit
  times a ratio (default 0.6), or a fixed fallback when the model is
  unknown.
- Over budget: compact further. If still over, fail the run as
  `context_exhausted`. The system prompt and the goal are never cut.
- Every tool call keeps its tool reply, so the request stays valid for the
  provider.
- A `context_compacted` event records each compaction with the token counts
  before and after.
- Settings: `keep_full_turns`, `context_budget_ratio`,
  `context_max_tokens`.

## Consequences

- Cost per turn levels off instead of growing.
- Long tasks no longer risk hitting the model's input limit.
- The model sees less old detail. The evals check that this does not hurt
  pass rates.

## Alternatives considered

- Summarize old turns with a model call. Rejected for now: costs a call and
  is not deterministic.
- Keep everything and raise `max_turns`. Rejected: cost grows with every
  turn.

## Implementation notes

- Code: `application/discovery/window.py` (the name `ContextBuilder` was
  already taken by the run-context factory). Token counting:
  `adapters/llm/litellm_client.py:LiteLlmTokenCounter`, behind the
  `TokenCounter` port, with a length estimate as the fallback.
- `context_compacted` is logged only when the budget forces fewer full
  digests than configured, not on every turn.
