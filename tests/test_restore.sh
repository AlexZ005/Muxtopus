#!/usr/bin/env bash
# mux-restore: the window snapshot, its freeze when the session is gone, and
# the restore that rebuilds the windows (docs/restore.md, docs/plan-restore.md).
# The sandbox of tests/notify_sandbox.sh on a socket of its own (-L mxrestore):
# a fake claude that records its argv and every key typed into it, a fake Bot
# API. Nothing here reaches a real pane, session, account or config.
#   bash tests/test_restore.sh
SB_SOCKET=mxrestore
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"; M="$REPO/muxtopus"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
SNAP="$ST/windows.tsv"; LAST="$ST/windows.last.tsv"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"
chmod 600 "$CLAUDE_NOTIFY_CONF"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
msgs() { sb_ncalls sendMessage; }
texts() { sb_calls sendMessage | jq -r .text; }
# A column of the row whose NAME is $1: col N of windows.tsv (1 wid 2 index
# 3 name 4 cwd 5 pane 6 sid 7 parent 8 model 9 effort 10 pmode 11 src 12 pid).
col() { awk -F'\t' -v n="$1" -v c="$2" '$3==n{print $c; exit}' "${3:-$SNAP}"; }
rows() { grep -vc '^#' "${1:-$SNAP}"; }
entry() {  # entry NAME cwd [extra header lines...]
  local n="$1" d="$2"; shift 2
  { printf 'type: work\nat: 2020-01-01 00:00\nslug: %s\ncwd: %s\n' "$n" "$d"
    for l in "$@"; do printf '%s\n' "$l"; done
    printf 'status: pending\n---\ncarry on\n'; } > "$SC/$n.md"
}
wait_launched() { for i in $(seq 40); do grep -q '^status: launched' "$SC/$1.md" && break; sleep 0.25; done; }
printf '● ready\n❯ \n' > "$HOME/fake-screen"
mkdir -p "$HOME/proj-a" "$HOME/proj-b"
"$W" --on >/dev/null

echo "== a pass writes one row per window of the session"
tmux new-session -d -s claude -n home -c "$HOME" -x 120 -y 40 "sleep 600"
tmux new-window -d -t claude -n plain -c "$HOME" "claude"
entry lane-a "$HOME/proj-a" 'model: fable' 'effort: high' 'permission-mode: bypassPermissions'
"$W" --once >/dev/null 2>&1; wait_launched lane-a
entry lane-b "$HOME/proj-b" 'parent: lane-a'
"$W" --once >/dev/null 2>&1; wait_launched lane-b
sleep 1
"$W" --once >/dev/null 2>&1
check "windows.tsv exists" test -f "$SNAP"
check "..with a #seen header" grep -q $'^#seen\t[0-9]' "$SNAP"
check "..and four rows" test "$(rows)" = 4
check "in index order" test "$(grep -v '^#' "$SNAP" | cut -f2 | paste -sd,)" = "0,1,2,3"
check "the home window: no session, the shell's cwd" test "$(col home 6)" = "-" -a "$(col home 4)" = "$HOME"
check "the hand-opened claude: a session id, no flags" bash -c '[[ "$1" == fake-* && "$2" == "-" ]]' _ "$(col plain 6)" "$(col plain 8)"
check "➥lane-a: its session id" bash -c '[[ "$1" == fake-* ]]' _ "$(col ➥lane-a 6)"
check "..its cwd from the session" test "$(col ➥lane-a 4)" = "$HOME/proj-a"
check "..model, effort, permission-mode from /proc/<pid>/cmdline" \
  test "$(col ➥lane-a 8)" = fable -a "$(col ➥lane-a 9)" = high -a "$(col ➥lane-a 10)" = bypassPermissions
check "..a root, launched from lane-a.md" test "$(col ➥lane-a 7)" = "-" -a "$(col ➥lane-a 11)" = lane-a.md
check "➥lane-b: parent lane-a, from the tree" test "$(col ➥➥lane-b 7)" = lane-a
check "..its pid is the fake claude's" kill -0 "$(col ➥➥lane-b 12)"
check "nothing frozen, nothing sent" test ! -f "$LAST" -a "$(msgs)" = 0

echo "== the server dies: the snapshot is frozen, not clobbered"
before="$(grep -v '^#' "$SNAP")"
command tmux -L "$SB_SOCKET" kill-server 2>/dev/null
sleep 0.5
"$W" --once >/dev/null 2>&1
check "windows.tsv is gone" test ! -f "$SNAP"
check "windows.last.tsv holds the same four rows" test "$(grep -v '^#' "$LAST")" = "$before"
check "..headed #lost <noticed> <last-seen>" grep -q $'^#lost\t[0-9]\+\t[0-9]\+$' "$LAST"
check "one log line says so" test "$(grep -c "tmux session 'claude' is gone: froze 4 window(s)" "$ST/log")" = 1
check "one message to the phone" test "$(msgs)" = 1
check "..naming the loss" grep -q "tmux session 'claude' lost" <<<"$(texts)"
"$W" --once >/dev/null 2>&1
"$W" --once >/dev/null 2>&1
check "two more passes: still one log line" test "$(grep -c 'is gone: froze' "$ST/log")" = 1
check "..still one message" test "$(msgs)" = 1
check "..the frozen file untouched" test "$(grep -v '^#' "$LAST")" = "$before"
check "muxtopus -l says so" grep -q "4 windows, frozen at" <<<"$("$M" -l 2>/dev/null)"

echo "== muxtopus -d never asks: off and ask make a plain session"
for mode in off ask; do
  setkey WATCHDOG_RESTORE "$mode"
  out="$("$M" -n -d 2>&1)"
  check "$mode: the session came up with its two default windows" \
    test "$(tmux list-windows -t claude -F '#{window_name}' | paste -sd,)" = "status,claude"
  check "$mode: the frozen file is untouched" test -f "$LAST"
  if [ "$mode" = ask ]; then check "ask: it said a snapshot is waiting" grep -q "is waiting -- muxtopus --restore" <<<"$out"; fi
  command tmux -L "$SB_SOCKET" kill-session -t claude 2>/dev/null; sleep 0.5
done

echo "== WATCHDOG_RESTORE=auto: muxtopus -d rebuilds the windows"
setkey WATCHDOG_RESTORE auto
sid_a="$(col ➥lane-a 6 "$LAST")"; sid_p="$(col plain 6 "$LAST")"; sid_b="$(col ➥➥lane-b 6 "$LAST")"
# Transcripts for two of the three sessions; lane-b's is gone.
mkdir -p "$HOME/.claude/projects/p"
: > "$HOME/.claude/projects/p/$sid_a.jsonl"; : > "$HOME/.claude/projects/p/$sid_p.jsonl"
rm -rf -- "${HOME:?}/proj-b"
rm -f "$HOME/fake-claude.argv" "$HOME/fake-claude.keys"
out="$("$M" -n -d 2>&1)"
check "muxtopus reported the restore" grep -q "restored 2 window(s) with their sessions, 2 plain" <<<"$out"
lw="$(tmux list-windows -t claude -F $'#{window_name}\t#{pane_current_path}')"
check "the windows, in the saved order, with their names" \
  test "$(cut -f1 <<<"$lw" | paste -sd,)" = "status,home,plain,➥lane-a,➥➥lane-b"
check "..in their saved cwds" test "$(awk -F'\t' '$1=="➥lane-a"{print $2}' <<<"$lw")" = "$HOME/proj-a" \
  -a "$(awk -F'\t' '$1=="plain"{print $2}' <<<"$lw")" = "$HOME"
check "..a gone cwd falls back to HOME, and the log says so" \
  test "$(awk -F'\t' '$1=="➥➥lane-b"{print $2}' <<<"$lw")" = "$HOME" -a "$(grep -c 'restore: ➥➥lane-b: .*proj-b is gone' "$ST/log")" = 1
argv="$(cat "$HOME/fake-claude.argv")"
check "➥lane-a resumed with its model, effort and permission mode" \
  grep -qx -- "--resume $sid_a --model fable --effort high --permission-mode bypassPermissions" <<<"$argv"
check "plain resumed with no flags" grep -qx -- "--resume $sid_p" <<<"$argv"
check "lane-b (no transcript) was not resumed" bash -c '! grep -q -- "$1" <<<"$2"' _ "$sid_b" "$argv"
check "..the log says which" grep -q "restore: ➥➥lane-b: no transcript for session $sid_b; a plain window" "$ST/log"
notes() { tr -d '\n\\' < "$HOME/fake-claude.keys" 2>/dev/null | grep -o 'restored after the tmux server was lost at' | wc -l; }
for i in $(seq 60); do [ "$(notes)" = 2 ] && break; sleep 0.25; done   # the fake drains a paste slowly
check "each resumed window got the note" test "$(notes)" = 2
check "the tree has lane-b under lane-a again" test "$(awk -F'\t' '$1=="lane-b"{print $2}' "$ST/tree.tsv")" = lane-a
check "..marked (restored)" test "$(awk -F'\t' '$1=="lane-a"{print $6}' "$ST/tree.tsv")" = "(restored)"
check "the frozen file became windows.restored.tsv" test ! -f "$LAST" -a -f "$ST/windows.restored.tsv"
check "the summary is in the log" grep -q "restore: done -- 2 resumed, 2 plain, 0 skipped, of 4 row(s)" "$ST/log"
"$W" --once >/dev/null 2>&1
check "the next pass snapshots the five windows" test "$(rows)" = 5
check "muxtopus -l: live" grep -q "5 windows, live" <<<"$("$M" -l 2>/dev/null)"
out="$("$W" --restore "$ST/windows.restored.tsv" 2>&1)"
check "a second restore of the same file skips the sessions already live" grep -q "2 already live" <<<"$out"

echo "== under auto the daemon itself relaunches muxtopus -d when the server goes"
"$W" --once >/dev/null 2>&1
command tmux -L "$SB_SOCKET" kill-server 2>/dev/null; sleep 0.5
"$W" --once >/dev/null 2>&1
check "the log says it relaunched" grep -q "WATCHDOG_RESTORE=auto: relaunching muxtopus -d" "$ST/log"
check "the session is back with its windows" bash -c 'tmux has-session -t claude 2>/dev/null && [ "$(tmux list-windows -t claude | wc -l)" -ge 4 ]'
check "..and the frozen file was consumed" test ! -f "$LAST" -a -f "$ST/windows.restored.tsv"

echo "== restoring into a session that already exists (the dashboard's row)"
setkey WATCHDOG_RESTORE ask
"$W" --once >/dev/null 2>&1
command tmux -L "$SB_SOCKET" kill-server 2>/dev/null; sleep 0.5
"$W" --once >/dev/null 2>&1
check "ask: the loss is frozen and stays frozen" test -f "$LAST" -a "$(rows "$LAST")" -ge 4
tmux new-session -d -s claude -n home -c "$HOME" -x 120 -y 40 "sleep 600"
"$W" --once >/dev/null 2>&1
check "the frozen file survives a pass with a fresh session" test -f "$LAST"
check "--restore into it says what it did" grep -q "^restored " <<<"$("$W" --restore 2>&1)"
command tmux -L "$SB_SOCKET" kill-server 2>/dev/null; sleep 0.5
rm -f "$SNAP"; "$W" --once >/dev/null 2>&1

echo "== the session is back: a live snapshot again, the loss cleared"
tmux new-session -d -s claude -n home -c "$HOME" -x 120 -y 40 "sleep 600"
"$W" --once >/dev/null 2>&1
check "windows.tsv is written again" test -f "$SNAP" -a "$(rows)" = 1
check "the phone hears cleared" grep -q "cleared: .*tmux session 'claude' lost" <<<"$(texts)"
sb_done
