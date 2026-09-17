#!/usr/bin/env bash
# Reset the mutable half of the fake machine between runs. EVERY deletion goes
# through "${SB:?}": with SB unset the expansion aborts the command rather
# than globbing from /. This is the ONLY place the sandbox deletes anything --
# an inline `rm $VAR/...` is the accident this rule exists to prevent.
set -euo pipefail
. "$(dirname "$0")/env.sh"
FIX="${SCRIPTS:?}/tests/fixtures/dashboard"
S="${SB:?}/muxhome/schedules-mxsplit"
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
sed -i "s|@SB@|${SB:?}|g; s|@SCRIPTS@|${SCRIPTS:?}|g" -- \
  "${S:?}"/*.md "${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"
