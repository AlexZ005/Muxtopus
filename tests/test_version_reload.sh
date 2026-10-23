#!/usr/bin/env bash
# A new release installed under a running watchdog is reloaded onto, without
# anyone running --reload: the daemon reads VERSION beside its script once per
# pass and re-executes itself (the SIGHUP path) one pass after it changed.
# claude-watchdog.sh version_point; docs/updates.md.
#
# The daemon runs from a COPY of this tree in the sandbox, so the test can
# rewrite its VERSION and break its script the way an install in progress
# would, without touching the checkout.
#   bash tests/test_version_reload.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
ST="$XDG_STATE_HOME/claude-watchdog"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }

LIB="$SB/lib"; mkdir -p "$LIB"
tar -C "$REPO" --exclude=.git --exclude=.venv --exclude=__pycache__ -cf - . | tar -C "$LIB" -xf -
W="$LIB/claude-watchdog.sh"
OLD="$(cat "$LIB/VERSION")"
logged() { local n; n="$(grep -c -- "$1" "$ST/log" 2>/dev/null)"; printf '%s' "${n:-0}"; }
# wait_for TEXT [N]: until the log holds TEXT (N times), up to 20 s.
wait_for() { local _; for _ in $(seq 80); do [ "$(logged "$1")" -ge "${2:-1}" ] && return 0; sleep 0.25; done; return 1; }

tmux new-session -d -s claude -n home -x 100 -y 30 "sleep 600"
setkey WATCHDOG_INTERVAL 1
"$W" --daemon >/dev/null 2>&1 & dpid=$!
SB_PIDS+=("$dpid")
wait_for "watchdog started"
check "the daemon is up" kill -0 "$dpid"

echo "== a new VERSION: said at once, reloaded one pass later"
echo 9.9.0 > "$LIB/VERSION"
check "it says the new release is installed" wait_for "muxtopus 9.9.0 is installed (this daemon runs $OLD): reloading onto it after the next pass"
check "..then reloads, naming old -> new" wait_for "reloading: muxtopus $OLD -> 9.9.0 installed"
check "..and is started again" wait_for "watchdog started" 2
check "..in the same process (exec, not a new daemon)" kill -0 "$dpid"
check "..whose pid file still names it" [ "$(cat "$ST/daemon.pid")" = "$dpid" ]
sleep 3
check "once: it does not reload again on 9.9.0" [ "$(logged 'reloading:')" = 1 ]

echo "== an install still being written: never exec'd into"
cp "$W" "$SB/good.sh"
printf 'if then fi (\n' >> "$W"
echo 9.9.1 > "$LIB/VERSION"
check "it waits: the script does not parse" wait_for "muxtopus 9.9.1 is installed, but $W does not parse yet -- staying on 9.9.0 until it does"
sleep 3
check "..said once" [ "$(logged 'does not parse yet')" = 1 ]
check "..no reload" [ "$(logged 'reloading:')" = 1 ]
check "..and the daemon is still passing" bash -c 'a=$(stat -c %Y "$1"); sleep 2.5; [ "$(stat -c %Y "$1")" -gt "$a" ]' _ "$ST/status.tsv"
cp "$SB/good.sh" "$W"
check "the script whole again: reloaded onto 9.9.1" wait_for "reloading: muxtopus 9.9.0 -> 9.9.1 installed"

echo "== an update that sends SIGHUP itself: one reload, not two"
# What `muxtopus update --apply` does once the files are in: --reload, which
# is this signal to the daemon's pid.
echo 9.9.2 > "$LIB/VERSION"; kill -HUP "$dpid"
check "the SIGHUP reload" wait_for "reloading: SIGHUP"
sleep 3
check "..and no version reload after it" [ "$(logged 'reloading: muxtopus 9.9.1 -> 9.9.2')" = 0 ]

echo "== the same VERSION: nothing"
n="$(logged 'reloading:')"; sleep 3
check "no reload while VERSION stays put" [ "$(logged 'reloading:')" = "$n" ]

kill "$dpid"; wait "$dpid" 2>/dev/null
sb_done
