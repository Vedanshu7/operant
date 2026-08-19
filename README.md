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
credentials by name, skip login when already logged in, never invent URLs).
It needs a model key and is opt-in, so it is off by default:

```bash
OPERANT_RUN_LLM_EVALS=1 uv run pytest tests/evals
```

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
