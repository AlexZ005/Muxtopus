#!/usr/bin/env bash
# SETTINGS ▸ NOTIFICATIONS, fired -- and the needs-you row.
#
# The goldens photograph the menu; this presses the rows that WRITE something
# and looks at what they wrote, the way actions.sh does for the schedule view.
# Four things (docs/notifications.md):
#
#   the submenu opens from Settings and is whole (no clipped tail)
#   a toggle round-trips to the file the sandbox WATCHDOG reads (profile.sh)
#   `Set up…` opens a window IN THE SANDBOX SERVER, running --setup
#   a `waiting` session is drawn yellow, as `needs you`
#
# SANDBOX DISCIPLINE. Its own SB, its own tmux server (-L mxnotifydash --
# kept apart from the -L mxnotify that tests/test_notify_*.sh kill-server at
# the end of) and its own session, so it runs beside either instead of
# killing it; a
# sandbox HOME, so CLAUDE_NOTIFY_CONF and every config path are fake. The
# real bot, the real conf and the real tmux server are unreachable from here
# -- `Set up…` starts the guide against a conf under $SB and nothing else.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export SB="${SB:-${TMPDIR:-/tmp}/muxnotify-sandbox}"
export SANDBOX_SOCKET=mxnotifydash SANDBOX_SESSION=mxnotifydash
. "$HERE/env.sh"

K="$HERE/k.sh"; C="$HERE/cap.sh"
WD="${SB:?}/state/claude-watchdog-mxsplit"
CONF="${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"
pass=0; fail=0

ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if "${@:2}"; then ok "$1"; else bad "$1"; fi; }

# Navigate by LOOKING, never by counting Downs: the mover skips separators,
# and how many a menu has is exactly what a later phase may change.
down_to() {
  local want="$1" i
  for i in $(seq 1 25); do
    if "$C" | grep -q "▸ .*$want"; then ok "cursor is on: $want"; return 0; fi
    PAUSE=0.15 "$K" Down
  done
  bad "never reached the row: $want"
  "$C" | grep -o "▸ .\{0,60\}" | tail -1
  return 1
}

# What profile.sh -- the half the WATCHDOG reads its switches with -- gets for
# a key in the sandbox. A value the menu wrote and this cannot see is a value
# no daemon will ever act on.
shell_val() {
  env -i HOME="$HOME" PATH="$PATH" \
      XDG_CONFIG_HOME="$XDG_CONFIG_HOME" XDG_STATE_HOME="$XDG_STATE_HOME" \
      MUXTOPUS_CONFIG="$MUXTOPUS_CONFIG" \
      bash -c '. "'"${SCRIPTS:?}"'/profile.sh"; mux_load_config mxsplit; printf "%s" "${'"$1"':-}"'
}

"$HERE/setup.sh" >/dev/null
"$HERE/clean.sh"

echo "== the submenu opens from Settings, and is whole"
"$HERE/start.sh" 58 >/dev/null
$K Escape
down_to "Settings ▸"
$K Enter
down_to "Notifications ▸"
$K Enter
sleep 0.4
"$C" > "${SB:?}/caps/notify-menu.txt"
check "the thirteen switches are all on the screen" bash -c '
  n=0; for k in "A window is waiting for you" "A lane has questions" "Trouble:" \
                "Say an entry is blocked after" "A lane finished" \
                "Let the phone answer" "Quote the prompt box" \
                "A session was lost: ON" "The account logged out: ON" \
                "A limit was hit: ON" "A budget crossed a band: off" \
                "An entry stalled: ON" "A lane is stranded: ON"; do
    grep -qF "$k" "'"${SB:?}"'/caps/notify-menu.txt" || { echo "missing: $k"; n=1; }
  done; [ "$n" = 0 ]'
check "..the status row says the backend is not configured" \
  grep -qF "Notifications: not configured" "${SB:?}/caps/notify-menu.txt"
check "..and Set up… and Send a test are offered" bash -c '
  grep -qF "Set up…" "'"${SB:?}"'/caps/notify-menu.txt" &&
  grep -qF "Send a test" "'"${SB:?}"'/caps/notify-menu.txt"'
check "the menu is drawn whole, hint and border and all" \
  python3 "$HERE/assert_menu.py" 58 "${SB:?}/caps/notify-menu.txt"

echo "== a toggle round-trips to the file the watchdog reads"
check "nothing is written yet"  bash -c '! grep -q MUXTOPUS_NOTIFY_PANE_TEXT "'"$CONF"'"'
[ "$(shell_val MUXTOPUS_NOTIFY_PANE_TEXT)" = "on" ] \
  && ok "..the shell half reads the default: on" \
  || bad "..the shell half reads the default: on (got '$(shell_val MUXTOPUS_NOTIFY_PANE_TEXT)')"
down_to "Quote the prompt box"
$K Enter
sleep 0.6
check "the notice names the file it wrote" \
  bash -c '"'"$C"'" | grep -qF "mxsplit.dashboard.conf"'
check "the row now reads off" bash -c '"'"$C"'" | grep -q "Quote the prompt box: off"'
check "..it is in the dashboard's own conf" \
  grep -q 'MUXTOPUS_NOTIFY_PANE_TEXT="off"' "$CONF"
[ "$(shell_val MUXTOPUS_NOTIFY_PANE_TEXT)" = "off" ] \
  && ok "..and profile.sh -- the watchdog's half -- reads off" \
  || bad "..and profile.sh -- the watchdog's half -- reads off (got '$(shell_val MUXTOPUS_NOTIFY_PANE_TEXT)')"
$K Enter
sleep 0.6
[ "$(shell_val MUXTOPUS_NOTIFY_PANE_TEXT)" = "on" ] \
  && ok "..and back on again" \
  || bad "..and back on again (got '$(shell_val MUXTOPUS_NOTIFY_PANE_TEXT)')"

echo "== the blocked-after row is minutes on disk and words on screen"
down_to "Say an entry is blocked after"
$K Enter
sleep 0.4
check "the picker offers words" bash -c '"'"$C"'" | grep -qE "never|30m|6h"'
$K Down; $K Enter
sleep 0.6
check "..and a number landed in the file" \
  grep -qE 'MUXTOPUS_NOTIFY_BLOCKED_AFTER="(0|30|60|120|360)"' "$CONF"

echo "== Set up… opens a window in the SANDBOX server"
down_to "Set up…"
$K Enter
sleep 1.2
check "the notice says where it went" bash -c '"'"$C"'" | grep -qF "notify-setup"'
check "a notify-setup window exists on the sandbox server" bash -c '
  tmux -L "'"${SANDBOX_SOCKET:?}"'" list-windows -t "'"${SANDBOX_SESSION:?}"'" -F "#{window_name}" | grep -qx notify-setup'
mux_tmux capture-pane -p -t "${SANDBOX_SESSION:?}:notify-setup" > "${SB:?}/caps/setup-window.txt" 2>/dev/null
check "..and it is the guide, waiting for an answer" \
  grep -qiE "notification|backend|telegram" "${SB:?}/caps/setup-window.txt"
# The guide writes a conf only at its last step, and nothing here answers it.
# What is proven is WHICH conf it would write: the env the dashboard handed
# the window, read back out of the window's own process.
check "..with CLAUDE_NOTIFY_CONF pointed inside the sandbox" bash -c '
  p=$(mux_tmux list-panes -t "'"${SANDBOX_SESSION:?}"':notify-setup" -F "#{pane_pid}" | head -1)
  for pid in $p $(pgrep -P "$p" 2>/dev/null); do
    tr "\0" "\n" < "/proc/$pid/environ" 2>/dev/null |
      grep -qx "CLAUDE_NOTIFY_CONF='"${SB:?}"'/notify.conf" && exit 0
  done; exit 1'
check "..and the real one was never opened" bash -c '
  ! grep -rqF "$HOME/.config/claude-notify.conf" "'"${SB:?}"'/caps/setup-window.txt"'
mux_tmux kill-window -t "${SANDBOX_SESSION:?}:notify-setup" 2>/dev/null

echo "== a waiting session is drawn yellow, as needs you"
$K Escape; $K Escape
printf 'gggg7777\twaiting-lane\t%%17\t2.0.1\t70000\twaiting\t\t\t0\t200000\t20000\t0\topus\t60\t\t%s/work/repo-a\t0\t0\t0\n' \
  "${SB:?}" >> "${WD:?}/status.tsv"
sleep 2.5
check "the STATE column says needs you, not waiting" bash -c '"'"$C"'" | grep -q "needs you"'
check "..in yellow (#d6b26b), the colour the screen uses for look-at-this" bash -c '
  "'"$C"'" -e | grep -a "needs you" | grep -qE "38;2;214;178;107|38;5;179"'

"$HERE/stop.sh" >/dev/null 2>&1

echo
if [ "$fail" = 0 ]; then echo "$pass passed"; else echo "$fail FAILED, $pass passed (sandbox: ${SB:?})"; fi
[ "$fail" = 0 ]
