#!/usr/bin/env bash
# install-hooks.sh — Install AWEP Claude CLI hooks into a settings.json
#
# Usage:
#   ./scripts/install-hooks.sh [API_URL] [OPTIONS]
#
# Options:
#   --with-context   Add UserPromptSubmit hook: inject recent conversation context
#   --with-topics    Add UserPromptSubmit hook: inject related-topic conversations (FTS5)
#
# Note: --with-context and --with-topics are alternatives; using both injects two
#       separate context blocks into every user turn.
#
# API_URL defaults to http://localhost:8001
# SETTINGS_FILE env var overrides the target settings file (default: ~/.claude/settings.json)
#   Example (MED project): SETTINGS_FILE=/path/to/MED/.claude/settings.json ./scripts/install-hooks.sh
#
# The script is idempotent: running it twice does not duplicate hooks.
# Requirements: jq (falls back to Python if jq is not found)

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

API_URL="http://localhost:8001"
WITH_CONTEXT=0
WITH_TOPICS=0

for arg in "$@"; do
  case "$arg" in
    --with-context) WITH_CONTEXT=1 ;;
    --with-topics)  WITH_TOPICS=1 ;;
    http*)          API_URL="$arg" ;;
  esac
done

SETTINGS_FILE="${SETTINGS_FILE:-$HOME/.claude/settings.json}"
# Absolute path to this AWEP installation (used to reference hook scripts)
AWEP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing AWEP hooks → $API_URL"
echo "Settings file: $SETTINGS_FILE"
echo "AWEP dir: $AWEP_DIR"
[[ $WITH_CONTEXT -eq 1 ]] && echo "Optional: UserPromptSubmit context hook"
[[ $WITH_TOPICS  -eq 1 ]] && echo "Optional: UserPromptSubmit topics hook"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

has_jq() { command -v jq &>/dev/null; }

# ---------------------------------------------------------------------------
# Base hooks (Stop / PreToolUse / PostToolUse) — always installed
# ---------------------------------------------------------------------------

merge_base_jq() {
  local tmp
  tmp=$(mktemp)
  jq --arg url "$API_URL" '
    .hooks //= {} |
    .hooks.Stop //= [] |
    if ([.hooks.Stop[].hooks[]? | select(.description? | test("awep-stop"))] | length) == 0
    then .hooks.Stop += [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST \($url)/ingest -H \"Content-Type: application/json\" -d @- > /dev/null 2>&1 || true",
        "description": "awep-stop: forward Stop hook to AWEP"
      }]
    }]
    else . end |
    .hooks.PreToolUse //= [] |
    if ([.hooks.PreToolUse[].hooks[]? | select(.description? | test("awep-pre"))] | length) == 0
    then .hooks.PreToolUse += [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "curl -sf -X POST \($url)/ingest -H \"Content-Type: application/json\" -d @- > /dev/null 2>&1 || true",
        "description": "awep-pre: forward PreToolUse hook to AWEP"
      }]
    }]
    else . end |
    .hooks.PostToolUse //= [] |
    if ([.hooks.PostToolUse[].hooks[]? | select(.description? | test("awep-post"))] | length) == 0
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

merge_base_python() {
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

def _add_ingest_hook(entries, tag, event):
    entries.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": f"curl -sf -X POST {api_url}/ingest -H 'Content-Type: application/json' -d @- > /dev/null 2>&1 || true",
            "description": f"{tag}: forward {event} hook to AWEP"
        }]
    })

for event, tag in [
    ("Stop",       "awep-stop"),
    ("PreToolUse", "awep-pre"),
    ("PostToolUse","awep-post"),
]:
    entries = hooks.setdefault(event, [])
    if not _has_awep(entries, tag):
        _add_ingest_hook(entries, tag, event)

with settings_path.open("w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("Base hooks installed (Python fallback).")
PYEOF
}

# ---------------------------------------------------------------------------
# Optional: UserPromptSubmit — context hook (recent conversation summaries)
# ---------------------------------------------------------------------------

install_context_hook_jq() {
  local tmp script_path
  tmp=$(mktemp)
  script_path="$AWEP_DIR/scripts/context_hook.py"
  jq --arg cmd "python3 ${script_path} 2>/dev/null || true" '
    .hooks.UserPromptSubmit //= [] |
    if ([.hooks.UserPromptSubmit[].hooks[]? | select(.description? | test("awep-context"))] | length) == 0
    then .hooks.UserPromptSubmit += [{
      "matcher": "",
      "hooks": [{"type": "command", "command": $cmd,
                 "description": "awep-context: inject recent conversation context"}]
    }]
    else . end
  ' "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
}

install_context_hook_python() {
  python3 - "$SETTINGS_FILE" "$AWEP_DIR" <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
awep_dir = sys.argv[2]
script_path = os.path.join(awep_dir, "scripts", "context_hook.py")

with settings_path.open(encoding="utf-8") as f:
    cfg = json.load(f)

hooks = cfg.setdefault("hooks", {})
entries = hooks.setdefault("UserPromptSubmit", [])

def _has_awep(entries, tag):
    for entry in entries:
        for h in entry.get("hooks", []):
            if tag in h.get("description", ""):
                return True
    return False

if not _has_awep(entries, "awep-context"):
    entries.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": f"python3 {script_path} 2>/dev/null || true",
            "description": "awep-context: inject recent conversation context"
        }]
    })

with settings_path.open("w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("Context hook installed (Python fallback).")
PYEOF
}

# ---------------------------------------------------------------------------
# Optional: UserPromptSubmit — topics hook (FTS5 keyword search; FAISS planned)
# ---------------------------------------------------------------------------

install_topics_hook_jq() {
  local tmp script_path
  tmp=$(mktemp)
  script_path="$AWEP_DIR/scripts/topic_hook.py"
  jq --arg cmd "python3 ${script_path} 2>/dev/null || true" '
    .hooks.UserPromptSubmit //= [] |
    if ([.hooks.UserPromptSubmit[].hooks[]? | select(.description? | test("awep-topics"))] | length) == 0
    then .hooks.UserPromptSubmit += [{
      "matcher": "",
      "hooks": [{"type": "command", "command": $cmd,
                 "description": "awep-topics: inject related-topic conversations"}]
    }]
    else . end
  ' "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
}

install_topics_hook_python() {
  python3 - "$SETTINGS_FILE" "$AWEP_DIR" <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
awep_dir = sys.argv[2]
script_path = os.path.join(awep_dir, "scripts", "topic_hook.py")

with settings_path.open(encoding="utf-8") as f:
    cfg = json.load(f)

hooks = cfg.setdefault("hooks", {})
entries = hooks.setdefault("UserPromptSubmit", [])

def _has_awep(entries, tag):
    for entry in entries:
        for h in entry.get("hooks", []):
            if tag in h.get("description", ""):
                return True
    return False

if not _has_awep(entries, "awep-topics"):
    entries.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": f"python3 {script_path} 2>/dev/null || true",
            "description": "awep-topics: inject related-topic conversations"
        }]
    })

with settings_path.open("w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("Topics hook installed (Python fallback).")
PYEOF
}

# ---------------------------------------------------------------------------
# Ensure settings file exists and is valid JSON
# ---------------------------------------------------------------------------

mkdir -p "$(dirname "$SETTINGS_FILE")"
if [[ ! -f "$SETTINGS_FILE" ]]; then
  echo '{}' > "$SETTINGS_FILE"
  echo "Created new settings file."
fi

if has_jq; then
  if ! jq empty "$SETTINGS_FILE" 2>/dev/null; then
    echo "ERROR: $SETTINGS_FILE is not valid JSON. Aborting." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Install base hooks
# ---------------------------------------------------------------------------

if has_jq; then
  merge_base_jq
  echo "Base hooks installed (jq)."
else
  echo "jq not found — using Python fallback."
  merge_base_python
fi

# ---------------------------------------------------------------------------
# Install optional hooks
# ---------------------------------------------------------------------------

if [[ $WITH_CONTEXT -eq 1 ]]; then
  if has_jq; then install_context_hook_jq; else install_context_hook_python; fi
  echo "Context hook installed."
fi

if [[ $WITH_TOPICS -eq 1 ]]; then
  if has_jq; then install_topics_hook_jq; else install_topics_hook_python; fi
  echo "Topics hook installed."
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
