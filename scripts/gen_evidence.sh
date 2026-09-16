#!/usr/bin/env bash
# Generate a demo evidence set: discover a capability, replay it, then
# replay it again with an injected session expiry.
#
# Usage: scripts/gen_evidence.sh [--profile ID] [--tenant ID]
#                                [--capability ID] [--goal TEXT]
#
# Run this from a Terminal that has been granted Accessibility AND Screen
# Recording (System Settings -> Privacy & Security), with the target app
# up. You approve each gated step at the y/n prompt; the discovery is a
# real LLM run, so it needs your model key in .env.
set -euo pipefail
cd "$(dirname "$0")/.."

# Defaults reproduce the README demo against the local ParaBank.
PROFILE="parabank"
TENANT="tenant-b"
CAP="savings-balance"
GOAL="Log in and read the current balance of the first account"
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --tenant) TENANT="$2"; shift 2 ;;
    --capability) CAP="$2"; shift 2 ;;
    --goal) GOAL="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

echo "==> 1/3 Discovery (real LLM; approve steps at the prompt)"
uv run operant discover --goal "$GOAL" --profile "$PROFILE" --tenant "$TENANT" --capability "$CAP"

echo "==> 2/3 Deterministic replay (no LLM)"
uv run operant replay "$CAP" --tenant "$TENANT"

EDGE=$(uv run python - "$CAP" <<'PY'
import json, sys, pathlib
cap = sys.argv[1]
root = pathlib.Path("artifacts") / cap
head = (root / "HEAD").read_text().strip()
doc = json.loads((root / f"v{head}.json").read_text())
path = doc.get("compiled_path") or []
print(path[1] if len(path) > 1 else (path[0] if path else ""))
PY
)
if [ -n "$EDGE" ]; then
  echo "==> 3/3 Error replay: inject session-expired before edge '$EDGE'"
  uv run operant replay "$CAP" --tenant "$TENANT" --inject "session-expired:$EDGE" || true
else
  echo "==> 3/3 skipped: no compiled edge found"
fi

echo "==> Done. Evidence in evidence/, artifact in artifacts/$CAP/."
