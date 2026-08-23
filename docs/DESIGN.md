# Design notes

This document explains how we approached the design, what we needed the
system to do, what qualities it had to have, and the trade-offs we made. It
uses plain language.

## How we started

We began from one sentence in the brief: the model discovers, the artifact
becomes a reusable capability, and deterministic replay is how the agent runs
it in production. Everything else follows from that.

That sentence has three parts, so we designed three things and the seams
between them:

1. A discovery loop that uses an LLM to drive a real screen.
2. A saved artifact that fully describes the flow, with a clear contract.
3. A replay engine that re-runs the artifact with no model.

We treated the artifact schema, the replay error handling, and the safety and
escalation model as the load-bearing parts, because the brief says those are
what the review focuses on. We kept everything else thin but real.

A second early decision was the surface. Banks run legacy web apps and native
desktop apps with no clean markup and no test IDs. A browser-only, DOM-based
approach would paint us into a corner. So we chose the macOS accessibility
tree as the surface. It works without a DOM and it exists on desktop apps
too, which matches the real environment better than a browser driver.

## Functional requirements

These are the things the system must do. They map to Section 3 of the brief.

- Take a goal in plain language plus a target, and run an observe, decide,
  act loop against a live screen until the goal is met or a stop condition
  is hit (max turns, timeout, or a dead end).
- Interact with a real UI: read state, click, type, and navigate.
- After a successful run, save a typed, versioned artifact that captures the
  ordered steps, how each control is found (with reasoning), the typed
  inputs, the typed outputs, and a checkpoint for success.
- Replay a saved artifact with input parameters and no model in the loop,
  using stable control targeting, and return the declared outputs.
- Classify the result: success with outputs, an expected business outcome, a
  recoverable condition, or a hard failure with enough detail to debug.
- Enforce an allowlist of apps, URLs, and action kinds.
- Treat risky and irreversible actions differently from safe ones.
- Never write secrets or raw sensitive data into artifacts or logs.
- Produce evidence for a run: a structured log plus a richer signal on
  failure, such as a screenshot.
- Detect when a run is stuck, route it to a human with context, let the human
  take over the same live session, and hand control back.
- Offer the saved capabilities to an agent as a catalog it can call by name
  with typed arguments.

## Non-functional requirements

These are the qualities the system must have, regardless of any single
feature.

- Determinism on replay. The same artifact and inputs must produce the same
  steps and outputs. No randomness, no model in the decision path.
- Safety by default. The system should refuse or pause on anything risky
  rather than guess. A person makes the call on gated steps.
- No secret leakage. Secrets are referenced by name. Values are resolved late
  by a trusted process and are redacted everywhere.
- Robustness to runtime errors. The interesting failures are not layout
  drift. They are validation errors, record-not-found, permission denials,
  surprise dialogs, session timeouts, and slow loads. Replay must notice
  these and act on purpose, not push blindly ahead.
- Extensibility without rewrites. Adding a new surface (a browser, Windows)
  or a new tenant should be a new adapter or a new binding, not a change to
  the engine or the schema.
- Observability. Every run leaves a readable trail so a person can understand
  and debug what happened.
- Testability. The core is pure and the edges are behind ports, so most
  behavior can be tested with fakes and no live services.
- Simple to run. One entry point, clear setup, and a way to run the tests
  without any live app, model, or network.

## Key trade-offs

Every choice below has a cost. We state the choice, why we made it, and what
we gave up.

- Accessibility tree over the DOM. It works on legacy and native apps with no
  clean markup, which is the real environment. The cost is that it is macOS
  only for now and the accessibility data can be uneven across apps. We
  accept that because the seam (the Surface port) lets us add other surfaces
  later without touching the core.

- In-process driver by default, with a daemon option. Running the driver in
  the same process is simple for local use. For Docker we expose the same
  surface over HTTP so the server can run in a container while the driver
  stays on the host where the OS permissions live. The cost is two ways to
  run it, but both share one Surface interface.

- SQLite for state, plain files for artifacts. Runs, approvals, and stability
  live in SQLite because they are queried and updated often. Artifacts,
  graphs, and profiles live as versioned JSON files because they are reviewed
  by humans and read by agents, and files are easy to diff and store in git.
  The cost is two stores, so `operant audit` cross-checks them.

- A synchronous engine with one thread per run. The engine blocks while it
  waits for a human, which is easy to read and reason about. The web server
  gives each run its own thread and bridges to the async layer in exactly one
  place. The cost is thread management, kept small and in one module.

- Keeping `from __future__ import annotations`. We adopted a strict vendored
  linter that normally bans it, but removing it broke forward references and
  caused name collisions across the code. We chose safety and made a small,
  documented exception in the linter.

- Content-addressed localization over title/URL matching. On replay we
  identify the live screen by a value-free structural fingerprint of its
  controls (role, name, label, and a coarse path, with digits and per-row
  values stripped), not by its title or URL. We do this because titles and
  URLs repeat across states — a bank's index page keeps its title logged in
  or out — so matching on them silently confuses look-alike pages. Fingerprints
  let replay resume from wherever the app already is: after the launch it
  re-localizes by content coverage, and when the app is past the recorded
  start (for example still logged in) it path-finds straight to the goal and
  skips the steps already done, instead of failing on absent login fields.
  The cost is a fingerprint stored per node and a coverage threshold to tune;
  we accept it because it replaced a brittle earlier scheme that marked a
  fixed resume point in advance and could not adapt to the live state.

- An affordance-navigation fallback at the goal. Content coverage can match
  the goal node while the page is only a shared look-alike — a menu that
  names the goal without being it. Rather than assert failure, replay clicks
  the live link whose name is the goal's own title (the "affordance" that
  reaches it) and then runs the goal assertion. The cost is one extra rule at
  the edge of the goal, but it keeps replay honest about arriving rather than
  guessing from a matching title.

- A typed result union instead of exceptions for outcomes. Success, business
  outcome, escalation, and failure are separate typed shapes. This forces the
  caller to handle "no such member" as a real answer, not a crash, which the
  brief calls out as the most common mistake. The cost is a little more code
  than raising an error.

- Human approves gated actions. The system routes risky steps to a person
  rather than letting the agent decide. This is safer for regulated data. The
  cost is that fully unattended discovery is not possible for gated steps,
  which is the correct trade for this domain.

## What we did not build

We kept these at a clean seam and wrote down why in REPORT.md:

- No browser or Windows surface yet. The Surface port is ready for them.
- No assisted LLM fallback on replay failure. Replay stays model-free for
  determinism. A stuck replay escalates to a human instead.
- No code generation from an artifact. The artifact is data, which keeps it
  reviewable.
- No tracing backend. The JSONL evidence log is the run record.
