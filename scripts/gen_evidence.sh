#!/usr/bin/env bash
# Generate the /evidence/ demo set against ParaBank (tenant-b).
#
# Run this from a Terminal that has been granted Accessibility AND Screen
# Recording (System Settings -> Privacy & Security), with ParaBank up
# (docker compose up -d parabank-b). You approve each gated step at the
# y/n prompt; the discovery is a real LLM run, so it needs your model key
# in .env (OPERANT_DISCOVERY__MODEL + ANTHROPIC_API_KEY).
set -euo pipefail
cd "$(dirname "$0")/.."

CAP="savings-balance"
GOAL="Log in and read the current balance of the first account"

echo "==> 1/3 Discovery (real LLM; approve steps at the prompt)"
uv run operant discover --goal "$GOAL" --profile parabank --tenant tenant-b --capability "$CAP"

echo "==> 2/3 Deterministic replay (no LLM)"
uv run operant replay "$CAP" --tenant tenant-b

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
  uv run operant replay "$CAP" --tenant tenant-b --inject "session-expired:$EDGE" || true
else
  echo "==> 3/3 skipped: no compiled edge found"
fi

echo "==> Done. Evidence in evidence/, artifact in artifacts/$CAP/."
echo "    Tell Claude to commit it, or: git add -f evidence artifacts/$CAP"
