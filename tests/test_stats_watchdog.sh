#!/usr/bin/env bash
# The watchdog's five-minute collect hook (docs/stats.md).
#
#   bash tests/test_stats_watchdog.sh
#
# The ledger has to accrue with the dashboard CLOSED, so the daemon runs
# `muxstats.py collect` -- but the daemon's real job is restarting a window
# that hit its limit at 4am, and this must never be able to stop that. So the
# two things proved here are:
#
#   * THE STAMP IS HONOURED. Twenty-two passes across eleven faked minutes
#     collect three times (at 0, 5 and 10 minutes), not twenty-two.
#   * A COLLECTOR FAILURE IS NOT A PASS FAILURE. With the collector made to
#     exit non-zero, the pass still returns 0, still publishes status.tsv and
#     still beats its heartbeat, and the log says what went wrong.
#
# SANDBOX DISCIPLINE (docs/contributing.md, "The sandbox"):
# its own HOME, XDG_CONFIG_HOME, XDG_STATE_HOME, MUXTOPUS_CONFIG and
# CLAUDE_CONFIG_DIR; a `tmux` wrapper pinned to -L mxstats so nothing here can
# reach `claude:0` or any window you are working in; a `python3` wrapper that
# records what the daemon ran and can be told to fail. The transcripts are the
# SYNTHETIC ones from tests/fixtures/transcripts/ -- no real transcript, no
# real state dir, no real config, no real schedules or handovers.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
W="$REPO/claude-watchdog.sh"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxstats-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share" XDG_RUNTIME_DIR="$SB/run"
export MUXTOPUS_CONFIG="$HOME/.config/muxtopus/config"
unset CLAUDE_CONFIG_DIR TMUX TMUX_PANE MUXTOPUS_HOME MUXTOPUS_PROFILES_DIR
for k in $(compgen -e); do
  case "$k" in WATCHDOG_*|DASHBOARD_*|MUXTOPUS_NOTIFY_*) unset "$k" ;; esac
done
mkdir -p "$HOME/.config/muxtopus" "$HOME/.claude/sessions" "$HOME/.claude/projects" \
         "$XDG_STATE_HOME" "$SB/run" "$SB/bin"
printf 'MUXTOPUS_HOME="%s"\nWATCHDOG_INTERVAL=1\n' "$HOME/.code" > "$MUXTOPUS_CONFIG"
mkdir -p "$HOME/.code/schedules" "$HOME/.code/handovers/done"

ST="$XDG_STATE_HOME/claude-watchdog"
LEDGER="$XDG_STATE_HOME/muxtopus/stats"
PYLOG="$SB/py.log"
FAILFLAG="$SB/make-muxstats-fail"

cleanup() {
  [ -n "${SLEEPER:-}" ] && kill "$SLEEPER" 2>/dev/null
  command tmux -L mxstats kill-server 2>/dev/null
  [ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"
}
trap cleanup EXIT

# tmux, pinned to a server of its own. Without this a stray send-keys reaches
# the window you are reading this in.
printf '#!/bin/sh\nexec %s -u -L mxstats -f /dev/null "$@"\n' "$(command -v tmux)" > "$SB/bin/tmux"
# ...and the same name handed to profile.sh's mux_tmux, which passes -L on
# every call: a later -L wins in tmux's own parsing, so a wrapper alone would
# be overridden by the watchdog's `-L default` and reach the real server.
export MUXTOPUS_TMUX_SOCKET=mxstats
# python3, recorded -- and, with the flag file there, made to fail the way a
# collector with a traceback in it would. The fault is injected at exactly the
# boundary claude-watchdog.sh guards, so what is being tested is the guard.
cat > "$SB/bin/python3" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$PYLOG"
case "\$*" in
  *muxstats.py*)
    if [ -f "$FAILFLAG" ]; then
      echo "muxstats: simulated collector failure" >&2
      exit 1
    fi ;;
esac
exec $(command -v python3) "\$@"
EOF
chmod +x "$SB/bin/tmux" "$SB/bin/python3"
export PATH="$SB/bin:$PATH"
# ...and named, because PATH alone no longer reaches it. The watchdog runs the
# python half through $MUX_PYTHON, which profile.sh resolves once from an
# ordered list of CANDIDATES -- a pinned one, the embedded one, the venv, then
# `python3` -- and each candidate is an absolute path or a probe of PATH taken
# before this stub was prepended. MUXTOPUS_PYTHON is the first of those
# candidates and the documented way to pin one, so it is how the stub gets
# chosen. Setting MUX_PYTHON directly would not survive: mux_resolve_python
# overwrites it unless _MUX_PY_TAKEN is already set.
export MUXTOPUS_PYTHON="$SB/bin/python3"

# A synthetic transcript, so a real collect has something to count. Copied from
# the fixtures the stats tests already use: invented projects, ids and counts
# with a real record's SHAPE.
cp -r "$REPO/tests/fixtures/transcripts/claude/projects/-home-user-proj-alpha" \
   "$HOME/.claude/projects/"

# A live process for the daemon to list, so a pass is doing its ordinary work
# while the collector is failing under it.
sleep 300 & SLEEPER=$!
printf '{"pid":%s,"sessionId":"deadbeef-0000-4000-8000-00000000dead","cwd":"%s","version":"0.0.0","status":"idle","kind":"interactive","tmux":""}\n' \
  "$SLEEPER" "$HOME" > "$HOME/.claude/sessions/$SLEEPER.json"

# grep -c PRINTS 0 and then EXITS 1 when it matches nothing, so a `|| echo 0`
# fallback appends a second zero and every "is it 0?" check fails.
ncollect() { local n; n="$(grep -c 'muxstats.py.*collect' "$PYLOG" 2>/dev/null)"; echo "${n:-0}"; }
pass1()    { "$W" --once >/dev/null 2>&1; echo $?; }

echo "== the collector runs on the first pass, and not on the second"
: > "$PYLOG"
rc="$(pass1)"
check "pass 1 returned 0"                     [ "$rc" = 0 ]
check "pass 1 collected once"                 [ "$(ncollect)" = 1 ]
check "pass 1 wrote the stamp"                [ -s "$ST/stats.at" ]
check "the ledger exists"                     [ -s "$LEDGER/ledger.tsv" ]
check "the ledger counted the fixture"        grep -q 'aaaaaaaa-0000-4000-8000-00000000000a' "$LEDGER/ledger.tsv"
check "the ledger has a meta"                 [ -s "$LEDGER/meta" ]
rc="$(pass1)"
check "pass 2 returned 0"                     [ "$rc" = 0 ]
check "pass 2 did NOT collect again"          [ "$(ncollect)" = 1 ]

echo "== eleven faked minutes of 30-second passes: three collects, not twenty-two"
# THE CLOCK IS NOT FAKED, THE STAMP IS. `date +%s` cannot be moved, so each
# pass is given a stamp aged exactly as it would be at that point on a 30s
# cadence -- which is the same arithmetic the hook does, asked from outside.
: > "$PYLOG"
rm -f "$ST/stats.at"
last=-1                       # faked seconds-since-start of the last collect
seen=0
at_minutes=""
for i in $(seq 0 21); do
  t=$(( i * 30 ))
  if [ "$last" -ge 0 ]; then
    printf '%s\n' $(( $(date +%s) - (t - last) )) > "$ST/stats.at"
  else
    rm -f "$ST/stats.at"
  fi
  before="$(ncollect)"
  "$W" --once >/dev/null 2>&1 || bad "pass at t=${t}s returned non-zero"
  if [ "$(ncollect)" != "$before" ]; then
    last="$t"; seen=$(( seen + 1 )); at_minutes="$at_minutes $(( t / 60 ))m"
  fi
done
check "22 passes over 11 minutes collected 3 times, at$at_minutes" [ "$seen" = 3 ]
check "the stamp survived every pass"         [ -s "$ST/stats.at" ]

echo "== a collector that fails does not fail the pass"
: > "$PYLOG"
touch "$FAILFLAG"
rm -f "$ST/stats.at" "$ST/heartbeat" "$ST/status.tsv"
rc="$(pass1)"
check "the pass still returned 0"             [ "$rc" = 0 ]
check "it did try to collect"                 [ "$(ncollect)" = 1 ]
check "status.tsv was still published"        [ -s "$ST/status.tsv" ]
check "the live session is still listed"      grep -q 'deadbeef-0000-4000-8000-00000000dead' "$ST/status.tsv"
check "the heartbeat still beat"              [ -s "$ST/heartbeat" ]
check "the log names the failure"             grep -q 'stats collect failed' "$ST/log"
check "the log says the ledger is unchanged"  grep -q 'The ledger is unchanged' "$ST/log"
check "the collector's stderr was kept"       grep -q 'simulated collector failure' "$ST/stats.err"
check "the stamp was written anyway"          [ -s "$ST/stats.at" ]
before="$(ncollect)"
"$W" --once >/dev/null 2>&1
check "a failure is retried in 5 min, not at once" [ "$(ncollect)" = "$before" ]
rm -f "$FAILFLAG"
rm -f "$ST/stats.at"
"$W" --once >/dev/null 2>&1
check "it recovers on the next due pass"      [ "$(ncollect)" != "$before" ]
check "the stale stats.err was removed"       [ ! -f "$ST/stats.err" ]

echo "== --dry-run prints what a pass would do, and does not collect"
: > "$PYLOG"
rm -f "$ST/stats.at"
"$W" --dry-run >/dev/null 2>&1
check "--dry-run returned 0"                  [ "$?" = 0 ]
check "--dry-run did NOT collect"             [ "$(ncollect)" = 0 ]
check "--dry-run wrote no stamp"              [ ! -f "$ST/stats.at" ]

echo "== the bound on a collector that HANGS is still in the source"
# A 120-second hang is not something a test may sit through, and rc 124 from
# `timeout` takes the same branch the simulated crash just proved. What a test
# can do cheaply is refuse to let the bound be deleted.
check "collect runs under timeout \$STATS_TIMEOUT" \
  grep -q 'timeout "\$STATS_TIMEOUT" "\$MUX_PYTHON" "\$SCRIPT_DIR/muxstats.py"' "$W"

echo "== the daemon collects too, and survives a failing collector"
: > "$PYLOG"
rm -f "$ST/stats.at"
touch "$FAILFLAG"
"$W" --daemon >/dev/null 2>&1 &
DAEMON=$!
sleep 3
check "the daemon is still running with a broken collector" kill -0 "$DAEMON" 2>/dev/null
check "the daemon tried to collect"           [ "$(ncollect)" -ge 1 ]
check "the daemon did not collect every pass" [ "$(ncollect)" -le 1 ]
kill "$DAEMON" 2>/dev/null; wait "$DAEMON" 2>/dev/null
rm -f "$FAILFLAG"

echo "== nothing outside the sandbox was touched"
check "no real state dir was created" [ ! -e "/home/$(id -un)/.local/state/muxtopus/stats/.mxstats-marker" ]
check "the sandbox owns the ledger"  bash -c 'case "$1" in "$2"/*) exit 0 ;; *) exit 1 ;; esac' _ "$LEDGER" "$SB"

echo
if [ "$FAILS" = 0 ]; then
  echo "$PASSES passed"
else
  echo "$FAILS FAILED, $PASSES passed (sandbox kept: $SB)"; KEEP_SANDBOX=1
fi
[ "$FAILS" = 0 ]
