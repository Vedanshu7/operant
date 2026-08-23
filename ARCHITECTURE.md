# Architecture

This document explains how Operant is put together and why. It uses plain
language so a new reader can follow it end to end.

## The big idea

Some bank and credit-union apps have no API. The only way in is to use the
screen like a person would. Operant does that in two phases:

1. Discover: an LLM looks at the live screen, decides the next action, and
   acts. It repeats until the goal is done. This happens once per task.
2. Replay: Operant saves what worked as a typed, versioned file called a
   capability, then re-runs that file with no model in the loop. Replay is
   what an AI agent calls in production. It is fast, cheap, and repeatable.

So the model discovers, the capability is the reusable result, and
deterministic replay is how the task runs every day after that.

## Layers

The code is split into layers. Each layer only knows about the layer below
it. This keeps the rules and the planning separate from how the screen is
read or where data is stored.

- domain: pure data and rules. The graph, the capability artifact, actions,
  targets, the policy, redaction, the secret grammar, the stability gate,
  and the error types live here. No input or output, no side effects.
- ports: small interfaces (Python Protocols) that the rest of the code talks
  to. Examples: Surface (read and act on a screen), Tool, SecretStore, the
  repositories, EvidenceSink, Approver, Clarifier, CredentialRequester, and
  LlmClient. Ports are the seams. You can swap a real thing for a fake
  without touching the core.
- application: the use cases and the engine. This holds the replay traversal,
  the LLM discovery loop, the recorder that turns a discovery into a graph,
  the control broker for human handoff, the approval gate, the secret
  resolver, the cross-run remediation memory, and the audit service.
- adapters: the edges that touch the outside world. The macOS accessibility
  surface (via xa11y), the HTTP driver daemon and the remote surface, the
  litellm client, the environment and Keychain secret stores, and the
  terminal human-in-the-loop.
- infra: settings, safe file writes, the JSONL evidence log, the SQLite
  database with Alembic migrations, and the file and database repositories.
- server: the operator web app. It runs each run on its own worker thread,
  streams events to the browser, and serves the `/api/v1` routes.
- cli: the `operant` command, one small file per subcommand.
- web: the React and TypeScript user interface.

## How discovery works

1. The caller gives a goal and a target (a profile, or bootstrap mode where
   the model picks the app).
2. The discovery loop takes a snapshot of the screen from the Surface. On
   macOS the Surface reads the accessibility tree, not the DOM, so it works
   on apps with no clean markup and on native apps.
3. If the app already has a graph, the loop localizes the live screen
   against it. When the screen matches a mapped state, it tells the model
   "you are already at known state X; skip the steps that lead here" and
   lists the moves already recorded from there. It also records this as a
   `localized` evidence event.
4. The loop sends the snapshot and the goal to the LLM and asks for one
   action.
5. Before any action runs, the policy checks it. Safe reads pass. Risky,
   mutating, or sensitive steps stop and ask a human to approve.
6. The action runs through the Surface. The recorder writes down the step,
   how the target control was found, and the reasoning.
7. When the goal is reached, the recorder compiles the steps into a graph and
   a capability artifact, and saves them.

The model never sees a real secret. It requests a credential by name through
a hidden channel (the `request_secret` tool) and only ever types a
placeholder like `$secret:password`. A human supplies the value, or names an
env/Keychain source, out of the model's sight (the web UI has a credential
card). The trusted process swaps the placeholder for the real value at the
moment of filling, and the value is never written to a log or an artifact.

## How replay works

1. The caller names a capability and gives typed inputs.
2. Operant loads the capability and its pinned graph. No model is involved.
3. Replay resumes from the live app state. Each graph node carries a
   value-free structural fingerprint of its screen (the accessibility
   control inventory with digits and values stripped). After the launch
   step the engine re-localizes the live screen by how much of a node's
   fingerprint it covers — content, not the title or URL, which repeat
   across states. If the app is already past the recorded start (for
   example still logged in) it path-finds straight to the goal and skips
   the steps already done, instead of failing on absent login fields. When
   the content matches the goal but the page is a shared look-alike (a menu
   that names the goal without being it), it clicks the live link named
   after the goal — an "affordance" — to actually arrive.
4. For each edge, the engine runs the same fixed steps: find the control,
   check the policy, act, wait for the screen to settle, then verify it
   reached the expected node. Targets are found by trying a ranked list of
   locator strategies in order, so the same graph produces the same actions.
5. The result is one of four typed shapes: success with outputs, a business
   outcome (a valid "no such record" answer), an escalation (a human took
   over), or a failure with a class, what was expected, and what was seen.

Across runs, a remediation memory remembers fixes for repeated step errors
and surfaces a matched remedy to discovery as a hint. It is advisory: a
remedy that keeps working is reinforced, and a stale one simply stops being
reinforced.

## The surface seam

The engine only knows the Surface port. It does not know about xa11y, a
browser, or an operating system. Today the one real Surface is macOS
accessibility. Adding a browser Surface (Playwright) or a Windows Surface is
a new adapter, not a change to the engine or the artifact.

A driver daemon exposes the same Surface over HTTP. That lets the server run
in a container while the one process that holds the macOS permissions runs on
the host.

## Where data lives

- Disk holds the source of truth for evidence, graphs, artifacts, and
  profiles. Artifacts and graphs are versioned JSON files.
- SQLite holds run state, the human-in-the-loop rows (approvals,
  interventions, clarifications), stability counts, and a searchable index of
  events.
- The `operant audit` command cross-checks the two so they cannot drift apart
  without being noticed.

## The web server and threads

The engine is synchronous and it blocks while it waits for a human decision.
The server gives each run its own worker thread so one blocked run does not
stop the others. There is exactly one place where a blocked worker thread
talks to the async web layer: a small bridge (`server/jobs`) that lets an
HTTP route deliver an answer to a waiting thread and stream events back to the
browser. Keeping that seam in one place keeps the rest simple.

## Human in the loop

When a run gets stuck, or hits a risky step, it hands control to a person. A
control broker makes sure only one side drives the session at a time. The
states are agent, paused, human, resuming, and back to agent. While a human
is in control the automation is blocked, so the two never fight over the
screen. Approvals are separate: for an approval the agent keeps control and
only waits for a yes or no.

## Safety in short

- The policy is an allowlist of apps, URLs, and action kinds.
- Risky, mutating, and sensitive steps need a human to approve.
- Secrets are referenced by name. The model never sees a value, and values
  never reach a log or an artifact.
- The web API and the driver daemon both require a bearer token.
