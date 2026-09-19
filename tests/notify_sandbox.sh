# tests/notify_sandbox.sh -- the sandbox every notify test runs in. SOURCE it.
#
# Sandbox discipline (docs/plan-dashboard-menus.md §5, docs/plan-notify-telegram.md §6):
# own HOME, XDG_CONFIG_HOME, XDG_STATE_HOME, MUXTOPUS_CONFIG, CLAUDE_CONFIG_DIR;
# a `tmux` wrapper pinned to -L mxnotify (SB_SOCKET); a fake `claude`; TELEGRAM_API at
# tests/fake_telegram.py; CLAUDE_NOTIFY_CONF at a sandbox file. Nothing here can
# reach the real bot, the real conf, or a pane of the real tmux server.
#
#   sb_init              make the sandbox, start the fake API (SB, FAKE set)
#   sb_calls METHOD      the recorded params of every call to METHOD, as JSON lines
#   sb_update JSON       append one scripted update
#   sb_cleanup           kill what was started (by pid), kill the -L server
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SB_PIDS=()
FAILS=0; PASSES=0

ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

sb_init() {
  SB="$(mktemp -d "${TMPDIR:-/tmp}/mxnotify-XXXXXX")"
  export HOME="$SB/home" XDG_CONFIG_HOME="$SB/home/.config" XDG_STATE_HOME="$SB/home/.local/state"
  export XDG_DATA_HOME="$SB/home/.local/share" XDG_RUNTIME_DIR="$SB/run"
  export MUXTOPUS_CONFIG="$SB/home/.config/muxtopus/config"
  export CLAUDE_NOTIFY_CONF="$SB/notify.conf"
  unset CLAUDE_CONFIG_DIR TMUX TMUX_PANE MUXTOPUS_HOME MUXTOPUS_PROFILES_DIR
  for k in $(compgen -e); do
    case "$k" in WATCHDOG_*|DASHBOARD_*|MUXTOPUS_NOTIFY_*) unset "$k" ;; esac
  done
  mkdir -p "$HOME/.config/muxtopus" "$HOME/.claude/sessions" "$XDG_STATE_HOME" "$SB/run" "$SB/bin" "$SB/fake"
  printf 'MUXTOPUS_HOME="%s"\n' "$HOME/.code" > "$MUXTOPUS_CONFIG"
  mkdir -p "$HOME/.code/schedules" "$HOME/.code/handovers/done" "$HOME/.local/bin"

  # tmux, pinned. Every call in the sandbox -- the watchdog's, muxtelegram's,
  # this file's -- lands on the private server.
  # SB_SOCKET: a test that runs beside the notify suite (test_restore.sh)
  # names a server of its own. The scripts' own calls carry the same name
  # through profile.sh's mux_tmux (MUXTOPUS_TMUX_SOCKET), so nothing this
  # sandbox starts can follow a pane's $TMUX to the real server.
  SB_SOCKET="${SB_SOCKET:-mxnotify}"
  export MUXTOPUS_TMUX_SOCKET="$SB_SOCKET"
  local real; real="$(command -v tmux)"
  printf '#!/bin/sh\nexec %s -u -L %s -f /dev/null "$@"\n' "$real" "$SB_SOCKET" > "$SB/bin/tmux"
  chmod +x "$SB/bin/tmux"
  # The fake claude: prints a prompt (or a scripted screen), publishes its
  # session file the way the real CLI does, and sits there.
  cat > "$SB/bin/claude" <<'EOF'
#!/bin/bash
# fake claude: record argv, publish sessions/<pid>.json, show $FAKE_SCREEN or a prompt.
printf '%s\n' "$*" >> "$HOME/fake-claude.argv"
cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
sid="fake-$$-$RANDOM"
mkdir -p "$cfg/sessions"
printf '{"pid":%s,"sessionId":"%s","cwd":"%s","version":"0.0.0","status":"idle","kind":"interactive","tmux":"%s"}\n' \
  "$$" "$sid" "$PWD" "sandbox:@0.${TMUX_PANE:-}" > "$cfg/sessions/$$.json"
trap 'rm -f "$cfg/sessions/$$.json"' EXIT
screen="${FAKE_SCREEN_FILE:-$HOME/fake-screen}"
last=""
while :; do
  cur="$(cat "$screen" 2>/dev/null)"
  if [ "$cur" != "$last" ]; then clear; printf '%s' "${cur:-❯ }"; last="$cur"; fi
  # keys typed into the pane are recorded, one per read
  if IFS= read -r -s -n1 -t 0.3 k; then printf '%q\n' "$k" >> "$HOME/fake-claude.keys"; fi
done
EOF
  chmod +x "$SB/bin/claude"
  cp "$SB/bin/claude" "$HOME/.local/bin/claude"
  export PATH="$SB/bin:$PATH"

  python3 "$REPO/tests/fake_telegram.py" "$SB/fake" >/dev/null 2>&1 &
  SB_PIDS+=($!)
  local i; for i in $(seq 50); do [ -f "$SB/fake/port" ] && break; sleep 0.1; done
  [ -s "$SB/fake/port" ] || { echo "the fake Bot API did not start -- refusing to run" >&2; exit 2; }
  export TELEGRAM_API="http://127.0.0.1:$(cat "$SB/fake/port")"
  export PUSHBULLET_API="$TELEGRAM_API"
  FAKE="$SB/fake"
  trap sb_cleanup EXIT
}

sb_calls() { [ -f "$FAKE/calls.jsonl" ] && jq -c --arg m "$1" 'select(.method==$m) | .params' "$FAKE/calls.jsonl"; return 0; }
sb_ncalls() { sb_calls "$1" | grep -c '' ; }
sb_update() { printf '%s\n' "$1" >> "$FAKE/updates.jsonl"; }

sb_cleanup() {
  local p
  for p in "${SB_PIDS[@]}"; do kill "$p" 2>/dev/null; done
  command tmux -L "$SB_SOCKET" kill-server 2>/dev/null
  [ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"
}

sb_done() {
  echo
  if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed (sandbox: $SB)"; KEEP_SANDBOX=1; fi
  [ "$FAILS" = 0 ]
}
