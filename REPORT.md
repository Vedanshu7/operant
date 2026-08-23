# Operant - design report

Operant automates tasks in applications that expose no API. An LLM discovers a
task once by observing and acting on the live UI; the system compiles what it
learned into a typed, versioned **capability**; and it then **replays** that
capability deterministically with no model in the loop. Every risky, mutating,
or sensitive step is gated by a human through a web UI. This report covers the
seven areas the design must answer.

## 1. Architecture

The code is layered so that policy, planning, and evidence never depend on how
the screen is actuated or where state is stored.

- `domain/` - pure models and rules: the graph, capability artifact, actions,
  targets, policy, redaction, sensitivity, governance gate, secret grammar,
  and the exception hierarchy. No I/O.
- `ports/` - `Protocol`s the rest of the system programs against: `Surface`,
  `Tool`, `SecretStore`, the repositories, `EvidenceSink`, `Approver`,
  `Clarifier`, `LlmClient`.
- `application/` - use cases and the engine: the replay traversal
  (`replay/`), the LLM discovery loop (`discovery/`), the recorder that turns a
  discovery into a graph, the control broker, the approval gate, the secret
  resolver, and the capability/audit services.
- `adapters/` - the edges: the macOS accessibility surface (`macos/` via
  `xa11y`), the HTTP driver daemon and remote surface, the litellm client, the
  env/Keychain secret stores, and the TTY human-in-the-loop.
- `infra/` - settings (`pydantic-settings`), atomic file helpers, the JSONL
  evidence log, the SQLite database and Alembic migrations, and the file/DB
  repositories.
- `server/` - the operator web app: a `RunManager` that runs each blocking run
  on its own worker thread, an `EventHub` that streams events to the browser
  over SSE, a `PendingAnswer` bridge that lets an HTTP route answer a blocked
  worker, and the `/api/v1` routes.
- `cli/` - the `operant` command (typer), one module per subcommand.
- `web/` - a React + TypeScript UI: type a goal, watch the run, and answer
  every approval, intervention, and clarifying question in the browser.

The engine is synchronous and blocks on human decisions, so the server gives
each run a thread and bridges the thread/async boundary in exactly one place
(`server/jobs/`). Graphs, artifacts, and profiles are versioned JSON on disk
behind repositories; SQLite holds run state, the human-in-the-loop rows,
stability counters, and the queryable event index. Disk is the source of
truth for evidence; the database is index and state; `operant audit`
cross-checks the two.

## 2. Artifact schema

Discovery produces a `CapabilityArtifact` (`domain/models/artifact.py`,
`SCHEMA_VERSION` 2.3): a typed, reviewable contract, not a script.

- **Identity & versioning** - `id`, monotonic `version`, `status`
  (`draft` → `approved`), the `vendor_id` graph it traverses, and the exact
  `graph_version` its path was compiled against.
- **Contract** - `inputs` and `outputs` as typed fields carrying a
  description, `required`, `sensitive`, and a `data_class`
  (`none`/`pii`/`financial`/`credential`), so the UI can render a form and
  redact the right values.
- **Path** - `start_node`, `goal_node`, and a `compiled_path` of edge ids; an
  empty path means "plan at run time". Nodes carry checkpoint checks (title,
  text, element) and a **value-free content fingerprint** of their screen
  (the accessibility control inventory with digits and per-row values
  stripped) that lets replay localize the live screen by content; edges carry
  an action, a target with **ordered locator strategies plus the model's
  reasoning**, a wait condition, and outcome detectors.
- **Bindings** - `tenants` map a tenant name to a base URL, an entry path, and
  secret-reference *names* (never values); `default_tenant`; and a
  `policy_scope` naming the app policy the run must satisfy.
- **Provenance** - the discovery run id, model, timestamp, and goal.

Capabilities live at `artifacts/<id>/vN.json` with a `HEAD` pointer;
approval writes a new version with `status = approved`. Stability is tracked
separately in SQLite so re-reading an artifact never rewrites it.

## 3. Determinism & error handling

Replay runs no model. `EdgeExecutor` drives every edge through the same fixed
sequence - **locate → policy check → perform → settle → verify arrival** -
and resolves targets by trying the compiled locator strategies in order, so
the same graph produces the same actions. The wall-clock budget excludes time
spent waiting on humans, so an approval never counts against a replay's
deadline.

Replay also resumes from the live app state. After a leading launch the
engine re-localizes the live screen by content-fingerprint coverage and,
when the app is already past the recorded start (e.g. still logged in),
path-finds straight to the goal and skips the steps already done rather than
failing on absent login fields; when the content matches the goal but the
page is a shared look-alike, it clicks the live link named after the goal (an
affordance) to arrive. This is the only place replay chooses a path, and it
does so structurally, with no model.

Outcomes are a typed union (`domain/models/results.py`), which is what makes
the three failure modes distinguishable:

- `SuccessResult` - reached the goal node; returns declared outputs.
- `BusinessOutcomeResult` - the app said no (e.g. `RECORD_NOT_FOUND`): a valid
  end state, not an error.
- `FailureResult` - a hard failure with a `failure_class`, the `expected` vs
  `observed` state, the edge, and evidence references.
- `EscalatedResult` - a human took over; carries the real intervention id and
  how it resolved.

Recoverable faults (e.g. a session that expired mid-run) are retried within a
bounded recovery budget before they become a hard failure or an escalation.

## 4. Heterogeneity & multi-tenant

The `Surface` port is the only thing the engine knows about actuation. Today
the sole real implementation is macOS accessibility (`xa11y`), which works
without a DOM and so generalises past the browser; a driver daemon exposes the
same surface over HTTP so the server (in a container) can reach the one
process that holds the OS permissions. Adding a Playwright or Windows surface
is a new adapter, not an engine change.

Multi-tenant reuse is a property of the artifact: one capability carries many
`TenantBinding`s. The same compiled path runs against ParaBank tenant A or
tenant B by swapping the base URL, entry path, and secret-reference names -
no re-discovery. App-wide knowledge (allowlists, mutating-control patterns,
window title, fault injection) lives once in the `AppProfile`, shared by every
capability for that vendor and editable in the UI.

## 5. Escalation & handoff

When a run gets stuck it does not fail blindly - it escalates to a live human.
The `ControlBroker` enforces that exactly one party controls the session at a
time: `agent → paused → human → resuming → agent`. While control is not the
agent's, the automation is structurally blocked, so it cannot act underneath
the operator. A separate, non-transferring slot carries approve/deny questions,
where the agent keeps control and only waits on permission.

In the web UI the operator sees an intervention card, **takes control** of the
live session, acts, and either **hands back** (the engine re-verifies state
before resuming, and the human's actions are recorded in the evidence) or
**abandons** the run. The server mirrors every broker transition into the
database and the SSE stream, so the browser reflects the live control state and
a reconnect replays it.

## 6. Safety

Safety is enforced at the actuation boundary and around secrets.

- **Allowlist & risk** - `domain/policy.py` evaluates every action against the
  app policy: allowed apps, URL patterns, and action kinds, plus which
  controls are mutating. Safe reads pass; risky actions become an approval.
- **Human-gated risk** - four gate kinds flow through the UI: `scope` (grant an
  app/URL into the allowlist), `mutating` (a state-changing control),
  `sensitive_fill`, and `sensitive_export` (sensitive data leaving the app).
  A decision can be remembered for the run; denials are never cached; a
  timeout is a denial.
- **Secrets never persist** - the model only ever sees `$secret:<name>`. The
  trusted process resolves the name to a value through the `SecretStore` (env
  or macOS Keychain) at the moment of filling, registers it with the redactor,
  and never writes it to an artifact, a log, or the event stream. Because the
  value is held only by the trusted process, secret-reference fills replay
  **unattended**; only model- or caller-supplied literal sensitive values stay
  gated.
- **Defence in depth** - the driver daemon builds its own redactor and requires
  a bearer token; the operator API is bearer-authenticated on every route;
  errors surface as `problem+json` without leaking internals.
- **Prompt-adherence evals** - an opt-in harness (`tests/evals/`, run with
  `OPERANT_RUN_LLM_EVALS=1`) drives discovery against the real model over
  synthetic screens and asserts on the tool-call trace: credentials go
  through `request_secret`, an already-logged-in screen is not
  re-authenticated, and URLs are never invented. It guards the system-prompt
  rules against regressions on any profile, not just ParaBank.

## 7. Cuts

Deliberately out of scope, with the reasoning:

- **Assisted LLM fallback on replay failure** - replay is intentionally
  model-free for determinism; a model-assisted recovery path is designed for
  but not built. Today a stuck replay escalates to a human instead.
- **Code generation of capabilities** - the artifact is data, not code, which
  keeps it reviewable and safe to store; emitting runnable code was not needed
  to meet the brief.
- **Non-macOS surfaces** - the `Surface` port is ready for Playwright/Windows
  adapters; only the macOS one is implemented.
- **Distributed / off-host driver** - the driver runs on the same host as the
  UI target because macOS grants permissions per launching app; a remote
  driver is a documented extension.
- **Tracing** - a Jaeger profile exists in compose, but OpenTelemetry export is
  not wired; the JSONL evidence log is the run record.
