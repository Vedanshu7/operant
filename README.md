# Operant

Operant runs tasks inside apps that have no API. It uses a model to figure out
the task once by looking at the screen and acting like a person. Then it saves
what worked as a typed, versioned capability and replays that capability with
no model in the loop. Every risky, mutating, or sensitive step pauses for a
human to approve.

More reading:

- [ARCHITECTURE.md](ARCHITECTURE.md): how the system is built.
- [docs/DESIGN.md](docs/DESIGN.md): the design approach, requirements, and
  trade-offs.
- [REPORT.md](REPORT.md): the design write-up with the seven required
  headings.
- [docs/conventions.md](docs/conventions.md): the coding standard the
  linter enforces.
- [docs/adr/](docs/adr/): design decisions, each with implementation notes:
  - [0001](docs/adr/0001-eval-harness-and-trials.md): eval harness and
    repeated trials.
  - [0002](docs/adr/0002-langfuse-observability.md): Langfuse for model
    observability.
  - [0003](docs/adr/0003-multi-agent-discovery.md): multi-agent discovery
    with fan-out.
  - [0004](docs/adr/0004-gepa-prompt-optimization.md): GEPA for prompt
    optimization.
  - [0005](docs/adr/0005-agent-memory-layer.md): agent memory layer.
  - [0006](docs/adr/0006-context-layer.md): context layer for model calls.
  - [0007](docs/adr/0007-local-pii-scrubbing-presidio.md): local PII
    scrubbing with Presidio.

## How it works, in three steps

1. Discover: the model drives the real screen through the macOS accessibility
   tree (no DOM needed) until the goal is done, and records what it did.
2. Compile: the recording becomes a capability. It has typed inputs and
   outputs, the path of steps, how each control is found, checkpoints, and
   per-tenant settings.
3. Replay: the capability runs again with no model. It resumes from
   wherever the app already is — after the launch it re-localizes the live
   screen by content, and if the app is already past the recorded start
   (for example still logged in) it path-finds straight to the goal and
   skips the steps already done. The same steps run the same way, and
   risky steps still pause for a human.

During discovery the model never sees a credential value. It requests one
by name (a `$secret:<name>` handle) and a human supplies the value, or
names an env/Keychain source, out of the model's sight. Replay resolves
those names late through the secret store.

## What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- Node 20 and pnpm to build or run the web UI.
- macOS for live runs. The driver needs Accessibility and Screen Recording
  permission. The test suite and a scripted replay run anywhere.
- A model API key, but only for discovery. Replay needs no key.

## Setup

```bash
uv sync                  # install Python dependencies
cp .env.example .env     # then put your ANTHROPIC_API_KEY in .env
uv run operant migrate   # create the database
```

Settings use the `OPERANT_` prefix with `__` for nesting. See `.env.example`.
The ones you are most likely to touch:

- `OPERANT_DISCOVERY__MODEL`: the model for discovery. Default is
  `anthropic/claude-haiku-4-5`. Set the matching key, for example
  `ANTHROPIC_API_KEY`.
- `OPERANT_SERVER__AUTH_TOKEN`: the API token. If you leave it blank, one is
  generated into `state/server-token` on first start.
- `OPERANT_SECRETS__BACKEND`: `env` (default) or `keychain`. App credentials
  are referenced by name and resolved at run time. They are never written to
  artifacts or logs.

## Run without any live services

You do not need macOS, a model, or a target app to check that it works:

```bash
uv run pytest                          # full Python test suite
cd web && pnpm install && pnpm test    # web tests
```

The server tests drive a full run over a scripted screen: start, a mutating
approval answered over HTTP, resume, and success. That is the same code path
the real UI uses.

A separate eval harness drives discovery against the real model over
synthetic screens to check it follows the system-prompt rules (request
credentials by name, skip login when already logged in). It needs a model key
and is opt-in, so it is off by default:

```bash
OPERANT_RUN_LLM_EVALS=1 uv run pytest tests/evals
```

Each scenario runs over three app skins (bank, CRM, HR) and several
trials, because the model is not deterministic:

- `OPERANT_EVAL_TRIALS` sets the trials per scenario (default 3).
- `OPERANT_EVAL_PASS_RATE` sets the pass rate each scenario must reach
  (default 0.67).
- Every trial is appended to `state/evals/<session>.jsonl`, and the run
  ends with a pass-rate table per scenario.
- The harness itself is tested in the normal suite with a scripted model.
- Each trial is also scored against a minimal reference trajectory
  (in-order recall, precision, efficiency), and in multi-agent mode the
  verifier's verdicts are labelled true or false accepts and rejects.
- `uv run python scripts/eval_report.py --set before=<jsonl> --set
  after=<jsonl>` prints the comparison tables.

## Demo path: discover then replay

The target for the demo is ParaBank, a public bank sandbox. Its demo login is
`john` / `demo` (already in `.env`).

Start ParaBank:

```bash
docker compose up -d parabank-b        # serves ParaBank on http://localhost:8081
```

Then, from a Terminal that has Accessibility and Screen Recording permission
(System Settings, Privacy and Security), run the whole demo with one script:

```bash
bash scripts/gen_evidence.sh
```

That does three things and writes evidence for each into `evidence/`:

1. A real discovery run that logs in and reads an account balance. You approve
   each gated step at the prompt.
2. A deterministic replay of the saved capability, with no model.
3. An error replay that injects a session expiry, to show how replay detects
   and reports an exceptional state.

You can also run the steps yourself:

```bash
uv run operant discover \
  --goal "Log in and read the current balance of the first account" \
  --profile parabank --tenant tenant-b --capability savings-balance

uv run operant replay savings-balance --tenant tenant-b
uv run operant replay savings-balance --tenant tenant-b --inject session-expired:<edge-id>
```

## The web UI

To use the operator UI (type a goal, watch runs, answer approvals):

```bash
uv run operant serve-driver --profile parabank   # terminal 1: the driver (needs permissions)
uv run operant serve                             # terminal 2: the API and UI
cd web && pnpm dev                               # terminal 3 (dev only): the UI on :5173
```

Open the UI, paste the token from `state/server-token` (or your
`OPERANT_SERVER__AUTH_TOKEN`), and start a run.

## Desktop app (Electron)

Operant also runs as a desktop app, so there are no terminals to juggle:

```bash
cd desktop && pnpm install && pnpm start   # builds the web UI, then opens the app
```

- The app starts `operant serve` itself, on a free local port with a fresh
  token each launch, and signs the UI in for you.
- The server drives the screen in-process, as a child of the app, so macOS
  asks for Accessibility and Screen Recording for the app instead of your
  terminal.
- Quitting the app stops the server. Server output goes to
  `state/desktop-server.log`.
- It runs Operant from this checkout with `uv`. A standalone `.dmg` (frozen
  Python sidecar, signed build) is the next step.

## Multi-agent discovery (optional)

`--agents multi` (or `OPERANT_DISCOVERY__AGENTS=multi`) runs a planner, the
usual executor, and a verifier panel
([ADR 3](docs/adr/0003-multi-agent-discovery.md)):

```bash
uv run operant discover --agents multi \
  --goal "Log in and read the current balance of the first account" \
  --profile parabank --tenant tenant-b --capability savings-balance
```

- The planner splits the goal into subgoals; only the executor touches the
  screen.
- The verifier panel checks each subgoal against the screen before the
  run moves on. Repeated rejections, a give-up, or a stall trigger a
  replan, then a human.
- Plans that worked and lessons from rejections are kept in SQLite per app
  ([ADR 5](docs/adr/0005-agent-memory-layer.md)), with every number masked.
- Models per role live in [`router.yml`](router.yml), a litellm Router
  config with one model group per role (`executor`, `planner`,
  `reviewer`), plus timeouts, retries and fallbacks. Point
  `OPERANT_DISCOVERY__ROUTER_CONFIG` at it; a missing group uses
  `executor`. Without it, `OPERANT_DISCOVERY__PLANNER_MODEL` and
  `__VERIFIER_MODEL` pick the models.
- Single-agent stays the default until the evals show multi-agent is at
  least as good on every family.

## Prompt optimization (optional)

GEPA tunes the prompts against the eval scenarios
([ADR 4](docs/adr/0004-gepa-prompt-optimization.md)):

```bash
uv sync --extra optimize
uv run python scripts/optimize_prompt.py --mode single --budget 150
```

It writes the best prompts, a diff, and validation scores to
`state/gepa/<time>/`. It never edits source: review `diff.patch`, apply it,
and re-run the evals.

## Model tracing (optional)

Discovery can trace every model call to a self-hosted Langfuse
([ADR 2](docs/adr/0002-langfuse-observability.md)):

```bash
uv sync --extra observability
# set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and the LANGFUSE_INIT_USER_*
# login in .env (see .env.example), then:
docker compose --profile observability up -d   # UI on http://localhost:3000
OPERANT_OBSERVABILITY__BACKEND=langfuse uv run operant discover ...
```

- One trace per run. The session is the run id, and the trace id is in the
  `discovery_started` evidence event.
- Secret values never reach Langfuse: the model only sees `$secret:<name>`.
- Prompts are sent after exact redaction and PII scrubbing.
  `OPERANT_OBSERVABILITY__CONTENT=metadata` sends only model, usage and tags.
- Evals tag their traces and attach a `passed` score and one score per check.

## PII scrubbing (optional)

Text that leaves the process or is stored can be scrubbed locally with
Presidio ([ADR 7](docs/adr/0007-local-pii-scrubbing-presidio.md)):

```bash
uv sync --extra privacy
# the spaCy model (about 500 MB); OPERANT_PRIVACY__SPACY_MODEL picks another
uv pip install "en_core_web_lg @ https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl"
uv run operant doctor   # reports whether the scrubber is ready
```

- `OPERANT_PRIVACY__SCRUBBER=auto` (default) uses Presidio when installed.
- Names, card numbers, IBANs, SSNs, emails and phone numbers become
  placeholders such as `<PERSON>`.
- The model that drives the screen is never scrubbed: it must read real
  labels to click the right control.
- `OPERANT_PRIVACY__EVIDENCE=scrubbed` also scrubs the evidence log
  (slower).

## Useful commands

```bash
uv run operant doctor                     # check config, permissions, tools
uv run operant catalog list               # list capabilities, stability, gate
uv run operant graph list                 # list saved app graphs
uv run operant audit --strict --evidence  # cross-check disk against the database
uv run i lint                             # run the linter (the coding standard)
```

## Layout

```
src/operant/  domain ports application adapters infra server cli
web/          the React and TypeScript UI
policies/ graphs/ artifacts/ evidence/ state/
```
