#!/usr/bin/env bash
# install-hooks.sh — Install AWEP Claude CLI hooks into ~/.claude/settings.json
#
# Usage:
#   ./scripts/install-hooks.sh [API_URL]
#
# API_URL defaults to http://localhost:8001
# The script is idempotent: running it twice does not duplicate hooks.
#
# Requirements: jq (falls back to Python if jq is not found)

set -euo pipefail

API_URL="${1:-http://localhost:8001}"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "Installing AWEP hooks → $API_URL"
echo "Settings file: $SETTINGS_FILE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

has_jq() { command -v jq &>/dev/null; }

# Merge hooks into settings using jq
merge_with_jq() {
  local tmp
  tmp=$(mktemp)
  jq --arg url "$API_URL" '
    # Ensure top-level hooks object exists
    .hooks //= {} |
    # Stop hook
    .hooks.Stop //= [] |
    if (.hooks.Stop | map(select(.command? | test("awep-stop"))) | length) == 0
    then .hooks.Stop += [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST \($url)/ingest -H \"Content-Type: application/json\" -d @- > /dev/null 2>&1 || true",
        "description": "awep-stop: forward Stop hook to AWEP"
      }]
    }]
    else . end |
    # PreToolUse hook
    .hooks.PreToolUse //= [] |
    if (.hooks.PreToolUse | map(select(.command? | test("awep-pre"))) | length) == 0
    then .hooks.PreToolUse += [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST \($url)/ingest -H \"Content-Type: application/json\" -d @- > /dev/null 2>&1 || true",
        "description": "awep-pre: forward PreToolUse hook to AWEP"
      }]
    }]
    else . end |
    # PostToolUse hook
    .hooks.PostToolUse //= [] |
    if (.hooks.PostToolUse | map(select(.command? | test("awep-post"))) | length) == 0
    then .hooks.PostToolUse += [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST \($url)/ingest -H \"Content-Type: application/json\" -d @- > /dev/null 2>&1 || true",
        "description": "awep-post: forward PostToolUse hook to AWEP"
      }]
    }]
    else . end
  ' "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
}

# Merge hooks into settings using Python (fallback)
merge_with_python() {
  python3 - "$SETTINGS_FILE" "$API_URL" <<'PYEOF'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
api_url = sys.argv[2]

with settings_path.open(encoding="utf-8") as f:
    cfg = json.load(f)

hooks = cfg.setdefault("hooks", {})

def _has_awep(entries, tag):
    for entry in entries:
        for h in entry.get("hooks", []):
            if tag in h.get("description", ""):
                return True
    return False

def _add_hook(entries, tag, event):
    entries.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": f"curl -sf -X POST {api_url}/ingest -H 'Content-Type: application/json' -d @- > /dev/null 2>&1 || true",
            "description": f"{tag}: forward {event} hook to AWEP"
        }]
    })

for event, tag in [("Stop", "awep-stop"), ("PreToolUse", "awep-pre"), ("PostToolUse", "awep-post")]:
    entries = hooks.setdefault(event, [])
    if not _has_awep(entries, tag):
        _add_hook(entries, tag, event)

with settings_path.open("w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("Done (Python fallback).")
PYEOF
}

# ---------------------------------------------------------------------------
# Ensure settings file exists
# ---------------------------------------------------------------------------

mkdir -p "$(dirname "$SETTINGS_FILE")"
if [[ ! -f "$SETTINGS_FILE" ]]; then
  echo '{}' > "$SETTINGS_FILE"
  echo "Created new settings file."
fi

# Validate JSON
if has_jq; then
  if ! jq empty "$SETTINGS_FILE" 2>/dev/null; then
    echo "ERROR: $SETTINGS_FILE is not valid JSON. Aborting." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Merge hooks
# ---------------------------------------------------------------------------

if has_jq; then
  merge_with_jq
  echo "Hooks installed (jq)."
else
  echo "jq not found — using Python fallback."
  merge_with_python
fi

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

echo ""
echo "Current hooks in $SETTINGS_FILE:"
if has_jq; then
  jq '.hooks | keys' "$SETTINGS_FILE" 2>/dev/null || true
else
  python3 -c "import json,sys; cfg=json.load(open(sys.argv[1])); print(list(cfg.get('hooks',{}).keys()))" "$SETTINGS_FILE"
fi

echo ""
echo "Done. Restart Claude CLI for hooks to take effect."
