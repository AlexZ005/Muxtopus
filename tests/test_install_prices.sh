#!/usr/bin/env bash
# Phase 6: install.sh seeds prices.md ONCE and never overwrites it.
#
#   bash tests/test_install_prices.sh
#
# The numbers in prices.md go out of date, the user is the one who updates
# them, and an installer that "refreshed" them would throw away an edit with
# no way to get it back. That is the options.md rule, and this file is the
# same proof for the second seeded file.
#
# It also checks the two things the seed has to be usable at all: muxstats
# parses it with no errors, and a report against it is priced rather than
# saying "no price". A seed the installer copies into every new machine and
# that nothing can read is worse than no seed.
#
# SANDBOX: its own HOME and XDG dirs, --no-watchdog so no service is installed
# and no daemon is started, and --bin inside the sandbox so no link is made on
# the real PATH. Nothing here touches the real config, the real ledger or the
# real systemd.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxprices-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share"
unset CLAUDE_CONFIG_DIR MUXTOPUS_CONFIG MUXTOPUS_HOME TMUX
mkdir -p "$HOME/.local/bin"
trap '[ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"' EXIT

PRICES="$HOME/.config/muxtopus/prices.md"
inst() { "$REPO/install.sh" --no-watchdog --home "$HOME/muxhome" --bin "$HOME/.local/bin" "$@"; }

echo "== a dry run touches nothing"
out="$(inst --dry-run 2>&1)"
check "the dry run names the file it would copy" grep -q "prices.md" <<<"$out"
check "...and wrote nothing"                     [ ! -e "$PRICES" ]

echo "== the first install seeds it"
out="$(inst 2>&1)"
check "install said it seeded prices.md" grep -q "prices.md seeded" <<<"$out"
check "the file is there"                [ -s "$PRICES" ]
check "it is the seed, byte for byte"    cmp -s "$REPO/seeds/prices.md" "$PRICES"
check "it names the date it was copied at" grep -q '^as of: ' "$PRICES"
check "options.md was seeded as well"    [ -s "$HOME/.config/muxtopus/options.md" ]

echo "== a second install leaves an EDITED file alone"
printf '\n# edited by hand\nmodel: my-local-model\ninput: 1\noutput: 2\ncache_read: 0.1\ncache_write_5m: 1.2\ncache_write_1h: 2\nwindow: 200K\n' >> "$PRICES"
sum="$(md5sum < "$PRICES")"
out="$(inst 2>&1)"
check "install said it left it alone"  grep -q "prices.md already exists" <<<"$out"
check "the edit survived byte for byte" [ "$(md5sum < "$PRICES")" = "$sum" ]
check "install did NOT say it seeded it" bash -c '! grep -q "prices.md seeded" <<<"$1"' _ "$out"
out="$(inst --dry-run 2>&1)"
check "a dry run over an existing file leaves it too" [ "$(md5sum < "$PRICES")" = "$sum" ]

echo "== the seed is a table muxstats can actually read"
check "no parse errors in the seed" \
  python3 -c "
import sys; sys.path.insert(0, '$REPO')
import muxstats
t = muxstats.prices('$REPO/seeds/prices.md')
assert t is not None, 'the seed did not parse at all'
assert not t.errors, t.errors
assert t.as_of, 'the seed has no \`as of:\` line'
assert len(t.models) >= 5, t.models
assert t.window('claude-opus-5'), 'no window for claude-opus-5'
"
check "the hand-edited block parses too" \
  python3 -c "
import sys; sys.path.insert(0, '$REPO')
import muxstats
t = muxstats.prices('$PRICES')
assert not t.errors, t.errors
assert 'my-local-model' in t.models, sorted(t.models)
"
check "a report against the seed is priced, not 'no price'" \
  bash -c "
    python3 '$REPO/tests/sandbox/mkledger.py' '$XDG_STATE_HOME/muxtopus/stats' >/dev/null &&
    python3 '$REPO/muxstats.py' stats --state-dir '$XDG_STATE_HOME/muxtopus/stats' \
      --no-collect --prices '$REPO/seeds/prices.md' --week |
      grep -q 'API-equiv'"
check "and without a price file it is tokens only, exit 0" \
  bash -c "
    python3 '$REPO/muxstats.py' stats --state-dir '$XDG_STATE_HOME/muxtopus/stats' \
      --no-collect --prices '$SB/nope.md' --week | grep -q 'no price'"

echo "== the collect hook cannot reach --check"
# claude-watchdog.sh --check resolves schedule entries and launches nothing; it
# returns before `pass`, so the new hook is not on that path at all. Proved
# against the SANDBOX's (empty) schedule folder -- the real entries are not
# this lane's to read.
printf 'MUXTOPUS_HOME="%s"\n' "$HOME/muxhome" > "$HOME/.config/muxtopus/config"
"$REPO/claude-watchdog.sh" --check >/dev/null 2>&1
rc=$?
check "--check on an empty schedule folder exits 0" [ "$rc" = 0 ]
check "--check collected nothing" [ ! -e "$XDG_STATE_HOME/claude-watchdog/stats.at" ]

echo
if [ "$FAILS" = 0 ]; then
  echo "$PASSES passed"
else
  echo "$FAILS FAILED, $PASSES passed (sandbox kept: $SB)"; KEEP_SANDBOX=1
fi
[ "$FAILS" = 0 ]
