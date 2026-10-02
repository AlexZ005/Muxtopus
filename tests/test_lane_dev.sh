#!/usr/bin/env bash
# lane-dev and `e2e-slot --dev`, driven against a real server.
#
#   bash tests/test_lane_dev.sh
#
# The "dev server" is python3's http.server on a free port, started through
# lane-dev's `-- command` form. A minute of idle is one second here
# (LANE_DEV_IDLE_UNIT), and the watcher polls every second. Its own
# XDG_STATE_HOME and its own lock files (E2E_SLOT_LOCK), so nothing here can
# touch a real lane's server or a real e2e slot. Every process it starts is
# a child it can name; nothing is signalled by pattern.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LD="$REPO/lane-dev"; ES="$REPO/e2e-slot"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxlanedev-XXXXXX")"
export XDG_STATE_HOME="$SB/state" LANE_DEV_POLL=1 LANE_DEV_IDLE_UNIT=1 LANE_DEV_WAIT=15
export E2E_SLOT_LOCK="$SB/e2e.lock"
ST="$XDG_STATE_HOME/lane-dev"
mkdir -p "$SB/app" "$SB/other"
FOREIGN=""
cleanup() {
  local d
  for d in "$ST"/*/; do [ -d "$d" ] && "$LD" stop "$(basename "$d")" >/dev/null 2>&1; done
  [ -n "$FOREIGN" ] && kill "$FOREIGN" 2>/dev/null
  [ -n "${KEEP:-}" ] || rm -rf -- "${SB:?}"
}
trap cleanup EXIT

free_port() {
  local p
  for p in $(shuf -i 20000-29999 -n 50); do
    (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null || { echo "$p"; return; }
  done
}
up() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
hit() { curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1/"; }
srv() { echo python3 -m http.server "$1" --bind 127.0.0.1; }
group_gone() { ! kill -0 -- "-$1" 2>/dev/null; }

P="$(free_port)"
echo "== start: returns once the port listens, in a session of its own"
out="$("$LD" start "$SB/app" "$P" --idle 0 -- $(srv "$P"))"; rc=$?
check "exit 0" [ "$rc" = 0 ]
check "the port answers" up "$P"
check "it says where and how long" grep -q "on port $P (pgid [0-9]*); stops after 0 min unused -- never" <<<"$out"
PG="$(cat "$ST/$P/pgid")"
check "the server leads its own group" [ "$(ps -o pgid= -p "$PG" | tr -d ' ')" = "$PG" ]
check "..and its own session, not this shell's" [ "$(ps -o sid= -p "$PG" | tr -d ' ')" = "$PG" ]
check "status lists it" grep -q "^$P .* $SB/app\$" <<<"$("$LD" status)"
check "status <dir> --quiet: 0" "$LD" status "$SB/app" --quiet
check "start again, same folder: already running, exit 0" grep -q "already running" <<<"$("$LD" start "$SB/app" "$P" -- $(srv "$P"))"
"$LD" start "$SB/other" "$P" -- $(srv "$P") >/dev/null 2>&1; rc=$?
check "the same port for another folder: refused, exit 3" [ "$rc" = 3 ]

echo "== stop, by folder: the whole group, and the record"
out="$("$LD" stop "$SB/app")"
check "it says so" grep -q "stopped $SB/app on port $P" <<<"$out"
check "the group is gone" group_gone "$PG"
check "the port is free" bash -c "! (exec 3<>/dev/tcp/127.0.0.1/$P) 2>/dev/null"
check "nothing recorded" [ ! -e "$ST/$P" ]
check "status <port> --quiet: 1" bash -c "! '$LD' status $P --quiet"
check "stop again: nothing to do, exit 0" "$LD" stop "$P"

echo "== a port held by something lane-dev did not start: refused"
P2="$(free_port)"
python3 -m http.server "$P2" --bind 127.0.0.1 >/dev/null 2>&1 & FOREIGN=$!
for i in $(seq 40); do up "$P2" && break; sleep 0.1; done
"$LD" start "$SB/app" "$P2" -- $(srv "$P2") >/dev/null 2>&1; rc=$?
check "exit 3" [ "$rc" = 3 ]
check "..and the foreign server is untouched" kill -0 "$FOREIGN"
kill "$FOREIGN"; FOREIGN=""

echo "== a server that dies at once: exit 1, with its output"
out="$("$LD" start "$SB/app" "$P" -- bash -c 'echo boom-from-the-server; exit 4' 2>&1)"; rc=$?
check "exit 1" [ "$rc" = 1 ]
check "its output is shown" grep -q boom-from-the-server <<<"$out"
check "nothing recorded" [ ! -e "$ST/$P" ]
"$LD" start "$SB" 1 2>/dev/null; rc=$?
check "no package.json and no command: refused, exit 2" [ "$rc" = 2 ]

echo "== the idle watcher: use keeps it, idleness stops it"
"$LD" start "$SB/app" "$P" --idle 4 -- $(srv "$P") >/dev/null
PG="$(cat "$ST/$P/pgid")"
for i in 1 2 3 4 5 6; do hit "$P"; sleep 1; done
check "six seconds of requests, idle 4: still running" up "$P"
for i in $(seq 40); do group_gone "$PG" && break; sleep 0.5; done
check "then unused: stopped by the watcher" group_gone "$PG"
check "..its record forgotten" [ ! -e "$ST/$P" ]
check "..after saying why, in the log it keeps" grep -q "idle 4 min: stopping" "$ST/$P.log"

echo "== the server never holds the caller's descriptors (an e2e slot is a flock)"
exec 8>"$SB/held.lock"; flock -n 8
"$LD" start "$SB/app" "$P" --idle 0 -- $(srv "$P") >/dev/null
exec 8>&-
check "the lock is free while the server still runs" flock -n "$SB/held.lock" true
"$LD" stop "$P" >/dev/null

echo "== e2e-slot --dev: up for the run, down after it"
# --dev has no `--` of its own, so the command comes from LANE_DEV_CMD.
export LANE_DEV_CMD='exec python3 -m http.server "$PORT" --bind 127.0.0.1'
out="$("$ES" --dev "$SB/app" "$P" -- bash -c "curl -s -o /dev/null -w 'served:%{http_code} ' http://127.0.0.1:$P/; echo slot:\$E2E_SLOT; exit 7" 2>/dev/null)"; rc=$?
check "the command ran against the server" grep -q "served:200" <<<"$out"
check "..in a slot" grep -q "slot:A" <<<"$out"
check "its exit code is the run's" [ "$rc" = 7 ]
check "the server is stopped after" bash -c "! (exec 3<>/dev/tcp/127.0.0.1/$P) 2>/dev/null"
check "..and forgotten" [ ! -e "$ST/$P" ]
check "the slot is free again" flock -n "$E2E_SLOT_LOCK" true
"$LD" start "$SB/app" "$P" --idle 0 -- $(srv "$P") >/dev/null
"$ES" --dev "$SB/app" "$P" -- true 2>/dev/null
check "a server that was already running is left running" up "$P"
"$LD" stop "$P" >/dev/null
"$ES" --exclusive --dev "$SB/app" "$P" -- bash -c 'echo $E2E_SLOT' >"$SB/excl.out" 2>/dev/null
check "--exclusive with --dev: both slots" grep -qx AB "$SB/excl.out"
LANE_DEV_CMD='exit 3' "$ES" --dev "$SB" "$P" -- touch "$SB/ran" 2>/dev/null; rc=$?
check "a server that cannot start fails the run" [ "$rc" = 1 ]
check "..and the command never ran" [ ! -e "$SB/ran" ]
exec 8>"$E2E_SLOT_LOCK"; flock -n 8; exec 9>"$E2E_SLOT_LOCK.b"; flock -n 9
"$ES" --wait 1 -- true 2>/dev/null; rc=$?
check "no slot free: exit 75, as before" [ "$rc" = 75 ]
exec 8>&- 9>&-

echo
if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed (sandbox: $SB)"; KEEP=1; fi
[ "$FAILS" = 0 ]
