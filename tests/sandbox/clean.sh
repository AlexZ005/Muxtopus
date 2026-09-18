#!/usr/bin/env bash
# Reset the mutable half of the fake machine between runs. EVERY deletion goes
# through "${SB:?}": with SB unset the expansion aborts the command rather
# than globbing from /. This is the ONLY place the sandbox deletes anything --
# an inline `rm $VAR/...` is the accident this rule exists to prevent.
set -euo pipefail
. "$(dirname "$0")/env.sh"
FIX="${SCRIPTS:?}/tests/fixtures/dashboard"
S="${SB:?}/muxhome/schedules-mxsplit"
H="${SB:?}/muxhome/handovers-mxsplit"
WD="${SB:?}/state/claude-watchdog-mxsplit"

rm -f -- "${S:?}"/*.md
cp -- "$FIX/muxhome/schedules-mxsplit"/*.md "${S:?}/"
rm -f -- "${WD:?}/optout" "${WD:?}/monitor-optout" "${WD:?}/usage.fail" \
         "${WD:?}/usage.hooray"
rm -f -- "${WD:?}/directives"/* 2>/dev/null || true
rm -f -- "${SB:?}/argv.log" "${SB:?}/home/.claude/sessions"/*.json
rm -f -- "${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"
cp -- "$FIX/config/muxtopus/profiles/mxsplit.dashboard.conf" \
      "${SB:?}/config/muxtopus/profiles/"
touch -- "${WD:?}/enabled" "${WD:?}/monitor"

# THE HANDOVERS, rebuilt and STAMPED. The handovers tab draws the age of
# every file, which is the wall clock against an mtime: a fixture copied at
# setup time reads "0s" on one run and "1s" on the next, and a golden cannot
# hold both. Fixed distances from NOW make the column reproducible and, as a
# bonus, realistic -- a screen of "0s" would have proved nothing about how
# the ages are drawn. The rows are also MOVED by the actions test (done,
# answered), so this is where the folder is put back.
rm -rf -- "${H:?}"
mkdir -p -- "${H:?}/done"
cp -- "$FIX/muxhome/handovers-mxsplit"/*.md "${H:?}/"
cp -- "$FIX/muxhome/handovers-mxsplit/done"/*.md "${H:?}/done/"
age() { touch -d "$2" -- "${H:?}/$1"; }
age QUESTIONS-root-lane.md             "2 hours ago"
age QUESTIONS-answered-lane.md         "4 days ago"
age STATUS-launched-lane.md            "12 minutes ago"
age STATUS-shadow-lane.md              "3 hours ago"
age STATUS-stranded-lane.md            "2 days ago"
age done/STATUS-root-lane.md           "1 day ago"
age done/STATUS-shadow-lane.md         "5 days ago"
age done/STATUS-old-lane-20260917-101500.md "6 days ago"
# THE LEGACY QUESTIONS FOLDER IS RESTORED TOO, because the handovers tab can
# now WRITE there: handover.sh does not own MUXTOPUS_QUESTIONS_DIR, so the
# ANSWERED marker for a file in it is written by muxhandovers directly. A run
# that marked one and did not put it back left the next run counting one
# fewer unanswered file, which is how this line came to be here.
Q="${SB:?}/muxhome/questions"
rm -rf -- "${Q:?}"
mkdir -p -- "${Q:?}"
cp -- "$FIX/muxhome/questions"/*.md "${Q:?}/"
touch -d "8 hours ago" -- "${Q:?}/QUESTIONS-launched-lane.md"
sed -i "s|@SB@|${SB:?}|g; s|@SCRIPTS@|${SCRIPTS:?}|g" -- \
  "${S:?}"/*.md "${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"
