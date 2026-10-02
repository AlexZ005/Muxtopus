#!/usr/bin/env bash
# install.sh links lane-dev and e2e-slot -- but never over a file of yours.
#
#   bash tests/test_install_lanetools.sh
#
# e2e-slot was a hand-made file in ~/.local/bin before it was versioned here,
# on the very machine it was versioned from. The rule under test: a free name
# gets the link; our own link (into this or another muxtopus checkout, or a
# dangling one) is refreshed; a FILE, or a link to somebody else's program,
# is left exactly as it was, and the installer says so.
#
# SANDBOX: its own HOME, --no-watchdog, --no-venv, --no-rc, --bin inside it.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxlanetools-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share"
unset CLAUDE_CONFIG_DIR MUXTOPUS_CONFIG MUXTOPUS_HOME TMUX
mkdir -p "$HOME"
trap '[ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"' EXIT
BIN="$HOME/.local/bin"
inst() { "$REPO/install.sh" --no-watchdog --no-venv --no-rc --home "$HOME/muxhome" --bin "$BIN" "$@"; }

echo "== a free name: linked"
out="$(inst 2>&1)"
check "lane-dev -> the checkout" [ "$(readlink "$BIN/lane-dev")" = "$REPO/lane-dev" ]
check "e2e-slot -> the checkout" [ "$(readlink "$BIN/e2e-slot")" = "$REPO/e2e-slot" ]
check "both said" [ "$(grep -c -- "-> $REPO/\(lane-dev\|e2e-slot\)" <<<"$out")" = 2 ]

echo "== a file of yours: left alone"
rm -f "$BIN/e2e-slot"; printf '#!/bin/sh\necho mine\n' > "$BIN/e2e-slot"; chmod +x "$BIN/e2e-slot"
out="$(inst 2>&1)"
check "still the file" [ ! -L "$BIN/e2e-slot" ] && grep -q mine "$BIN/e2e-slot"
check "..and the installer says so" grep -q "$BIN/e2e-slot is not ours (a file), leaving it alone" <<<"$out"
check "lane-dev is still linked" [ "$(readlink "$BIN/lane-dev")" = "$REPO/lane-dev" ]

echo "== a link to somebody else's program: left alone"
mkdir -p "$SB/elsewhere"; printf '#!/bin/sh\n' > "$SB/elsewhere/lane-dev"
ln -sfn "$SB/elsewhere/lane-dev" "$BIN/lane-dev"
out="$(inst 2>&1)"
check "still theirs" [ "$(readlink "$BIN/lane-dev")" = "$SB/elsewhere/lane-dev" ]

echo "== our own link, from another checkout or dangling: refreshed"
mkdir -p "$SB/old-checkout"; : > "$SB/old-checkout/muxtopus"; : > "$SB/old-checkout/lane-dev"
ln -sfn "$SB/old-checkout/lane-dev" "$BIN/lane-dev"
ln -sfn "$SB/gone/e2e-slot" "$BIN/e2e-slot"
inst >/dev/null 2>&1
check "another muxtopus checkout's link: now this one" [ "$(readlink "$BIN/lane-dev")" = "$REPO/lane-dev" ]
check "a dangling link: now this one" [ "$(readlink "$BIN/e2e-slot")" = "$REPO/e2e-slot" ]

echo
if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed (sandbox: $SB)"; KEEP_SANDBOX=1; fi
[ "$FAILS" = 0 ]
