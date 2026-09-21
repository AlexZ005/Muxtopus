#!/usr/bin/env bash
# mux-alerts phase 2: `rc: on|off`, applied by the LAUNCHER after readiness,
# with DASHBOARD_NEW_RC as the default for entries that do not say. The sandbox
# of tests/notify_sandbox.sh (-L mxnotify, a fake claude that records every key
# typed into it); nothing here reaches a real pane or schedule.
#   bash tests/test_sched_rc.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
entry() {  # entry NAME [rc-value]
  { printf 'type: work\nat: 2020-01-01 00:00\nslug: %s\ncwd: %s\n' "$1" "$HOME"
    [ -n "${2:-}" ] && printf 'rc: %s\n' "$2"
    printf 'status: pending\n---\ncarry on\n'; } > "$SC/$1.md"
}
check_rc() { "$W" --check "$SC/$1.md" 2>/dev/null | awk '$1=="rc"{sub(/^ *rc +/,""); print}'; }
printf '● ready\n❯ \n' > "$HOME/fake-screen"
tmux new-session -d -s claude -n home -x 120 -y 40 "sleep 600"
"$W" --on >/dev/null

echo "== --check reports the resolved value"
entry plain; entry yes on; entry no off; entry odd maybe
check "no header, no setting: off (default)" grep -q "^off .*DASHBOARD_NEW_RC=off" <<<"$(check_rc plain)"
check "rc: on" grep -q "^on .*rc: on in the entry" <<<"$(check_rc yes)"
check "rc: off" grep -q "^off .*rc: off in the entry" <<<"$(check_rc no)"
check "an odd value: the default, and said so" grep -q 'rc: "maybe" is not on or off' <<<"$(check_rc odd)"
setkey DASHBOARD_NEW_RC on
check "Settings default on: an entry that does not say gets it" grep -q "^on .*the Settings default" <<<"$(check_rc plain)"
check "..and rc: off still wins" grep -q "^off .*rc: off in the entry" <<<"$(check_rc no)"
check "..an odd value takes the default: on" grep -q "^on " <<<"$(check_rc odd)"
setkey DASHBOARD_NEW_RC off
rm -f "$SC"/*.md

launch() {  # launch NAME [rc]: one entry, one pass, the keys that window got
  rm -f "$HOME/fake-claude.keys"; entry "$@"
  "$W" --once >/dev/null 2>&1
  for i in $(seq 40); do grep -q '^status: launched' "$SC/$1.md" && break; sleep 0.25; done
  # The fake drains the paste one key per loop, a fork each; wait for the
  # body to have arrived rather than guess how long the identity lines take.
  for i in $(seq 40); do tr -d '\n' < "$HOME/fake-claude.keys" 2>/dev/null | grep -q carry && break; sleep 0.25; done
}

echo "== the launcher: rc: on sends /rc before the paste"
launch lane-on on
check "launched" grep -q '^status: launched' "$SC/lane-on.md"
k="$(tr -d '\n' < "$HOME/fake-claude.keys" 2>/dev/null)"
check "the window received /rc" grep -qF '/rc' <<<"$k"
check "..BEFORE the body" bash -c '[[ "$1" == *"/rc"*"carry"* ]]' _ "$k"
check "the log says so" grep -q "schedule lane-on.md: sent /rc to" "$ST/log"
check "the launch line records rc=on" grep -q "launched lane-on.* rc=on" "$ST/log"

echo "== rc: off, and no header with the default off: no /rc"
launch lane-off off
check "rc: off: no /rc" bash -c '! tr -d "\n" < "$1" | grep -qF "/rc"' _ "$HOME/fake-claude.keys"
launch lane-plain
check "no header: no /rc" bash -c '! tr -d "\n" < "$1" | grep -qF "/rc"' _ "$HOME/fake-claude.keys"
check "and no rc=on in its launch line" bash -c '! grep -q "launched ➥lane-plain.*rc=on" "$1"' _ "$ST/log"

echo "== DASHBOARD_NEW_RC=on: every new window, no per-entry edit"
setkey DASHBOARD_NEW_RC on
launch lane-dflt
check "no header, default on: /rc sent" bash -c 'tr -d "\n" < "$1" | grep -qF "/rc"' _ "$HOME/fake-claude.keys"
launch lane-optout off
check "rc: off beats the default" bash -c '! tr -d "\n" < "$1" | grep -qF "/rc"' _ "$HOME/fake-claude.keys"

echo "== a panel /rc leaves up is closed before the paste"
setkey DASHBOARD_NEW_RC off
rm -f "$HOME/fake-claude.keys"; entry lane-panel on
# The fake draws a panel holding the keyboard as soon as /rc has been typed at
# it. The trigger is the /rc itself, not "any key": the previous window's fake
# is still draining its own paste into the same keys file when this starts,
# and a panel drawn before the new window exists is a window that never
# shows a prompt.
( for i in $(seq 150); do tr -d '\n' < "$HOME/fake-claude.keys" 2>/dev/null | grep -qF '/rc' && break; sleep 0.1; done
  printf 'Remote Control\n  session url ...\n  Esc to close\n' > "$HOME/fake-screen" ) &
"$W" --once >/dev/null 2>&1
check "the panel was seen and Escaped" grep -q "schedule lane-panel.md: /rc left a dialog or panel up" "$ST/log"
esc="\$'\\E'"      # how the fake's printf %q writes the ESC byte
check "an Escape reached the window" grep -qF -- "$esc" "$HOME/fake-claude.keys"
check "and it still launched" grep -q '^status: launched' "$SC/lane-panel.md"
printf '● ready\n❯ \n' > "$HOME/fake-screen"
sb_done
