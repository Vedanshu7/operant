# Operator guide

Settings, the ways to run Operant, and the optional features. Start
with the [README](../README.md).

## Settings

Settings use the `OPERANT_` prefix with `__` for nesting. See `.env.example`.
The ones you are most likely to touch:

- `OPERANT_DISCOVERY__MODEL`: the model for discovery. Default is
  `anthropic/claude-haiku-4-5`. Set the matching key, for example
  `ANTHROPIC_API_KEY`.
- `OPERANT_SERVER__AUTH_TOKEN`: the API token. If you leave it blank, one is
  generated into `state/server-token` on first start.
- `OPERANT_DRIVER__AUTH_TOKEN`: the driver daemon's token. If you leave it
  blank, the daemon and local clients share one generated into
  `state/driver-token`. Set it when the driver runs on another machine.
- `OPERANT_SECRETS__BACKEND`: `env` (default) or `keychain`. App credentials
  are referenced by name and resolved at run time. They are never written to
  artifacts or logs.

## The web UI

To use the operator UI (type a goal, watch runs, answer approvals):

```bash
uv run operant serve-driver --profile parabank   # terminal 1: the driver (needs permissions)
uv run operant serve                             # terminal 2: the API and UI
cd web && pnpm dev                               # terminal 3 (dev only): the UI on :5173
```

Open the UI, paste the token from `state/server-token` (or your
`OPERANT_SERVER__AUTH_TOKEN`), and start a run.

## Desktop app

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
  `desktop-server.log` in the app's log folder (`~/Library/Logs/<app>`).
- It runs Operant from this checkout with `uv`. A standalone `.dmg` (frozen
  Python sidecar, signed build) is the next step.

## Multi-agent discovery

`--agents multi` (or `OPERANT_DISCOVERY__AGENTS=multi`) runs a planner, the
usual executor, and a verifier panel
([ADR 3](adr/0003-multi-agent-discovery.md)):

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
- Plans that worked, and lessons from subgoals the run kept failing, are
  kept in SQLite per app ([ADR 5](adr/0005-agent-memory-layer.md)),
  with every number masked. Lessons are decided when the run ends, so a
  rejection the run got past teaches nothing. `operant memory list`
  shows what is remembered; `operant memory forget --app <id>` clears
  it.
- Models per role live in [`router.yml`](../router.yml), a litellm Router
  config with one model group per role (`executor`, `planner`,
  `reviewer`), plus timeouts, retries and fallbacks. Point
  `OPERANT_DISCOVERY__ROUTER_CONFIG` at it; a missing group uses
  `executor`. Without it, `OPERANT_DISCOVERY__PLANNER_MODEL` and
  `__VERIFIER_MODEL` pick the models.
- Single-agent stays the default until the evals show multi-agent is at
  least as good on every family.

## Prompt optimization

GEPA tunes the prompts against the eval scenarios
([ADR 4](adr/0004-gepa-prompt-optimization.md)):

```bash
uv sync --extra optimize
uv run python scripts/optimize_prompt.py --mode single --budget 150
```

It writes the best prompts, a diff, and validation scores to
`state/gepa/<time>/`. It never edits source: review `diff.patch`, apply it,
and re-run the evals.

## Model tracing

Discovery can trace every model call to a self-hosted Langfuse
([ADR 2](adr/0002-langfuse-observability.md)):

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

## PII scrubbing

Text that leaves the process or is stored can be scrubbed locally with
Presidio ([ADR 7](adr/0007-local-pii-scrubbing-presidio.md)):

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
- Screenshots black out password and other sensitive fields before they are
  sent to the model or saved as evidence.
- `OPERANT_PRIVACY__EVIDENCE_RETENTION_DAYS=30` sets how long
  `operant evidence prune` keeps a run's evidence.

## Commands

Tests run anywhere, with no macOS, model or target app. The server tests
drive a full run over a scripted screen, including an approval answered
over HTTP.

```bash
uv run pytest                          # Python tests
cd web && pnpm install && pnpm test    # web tests
```


```bash
uv run operant doctor                     # check config, permissions, tools
uv run operant catalog list               # list capabilities, stability, gate
uv run operant catalog canary             # replay approved read-only capabilities once
uv run operant graph list                 # list saved app graphs
uv run operant evidence prune --days 30  # delete evidence runs older than 30 days
uv run operant audit --strict --evidence  # cross-check disk against the database
uv run i lint                             # run the linter (the coding standard)
```

A capability is approved on its last 20 replays, not its lifetime. Three
failed replays in a row move an approved capability to `degraded`, which stops
unattended replays until a person approves it again. Run the canary on a
schedule to find a broken capability before anyone needs it, for example hourly
from cron:

```bash
0 * * * * cd /path/to/operant && uv run operant catalog canary
```
