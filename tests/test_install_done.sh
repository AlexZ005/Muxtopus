#!/usr/bin/env bash
# install.sh: the last screenful says whether muxtopus can run, and what to
# paste if it cannot yet.
#
#   bash tests/test_install_done.sh
#
# The transcript that prompted this ended "Done. Start with: muxtopus" on a
# box whose tmux was 3.0a and whose `claude` sat in ~/.local/bin, off PATH.
# Both were reported -- forty lines up, in step 1 of 7 -- and the user read
# the end. The rules under test:
#
#   - a claude that is installed but off PATH is NAMED, and is not a blocker:
#     step 4 puts $BIN on PATH and muxtopus puts ~/.local/bin on its own;
#   - a claude that is nowhere, or a tmux older than 3.2, is repeated under
#     "Done, but muxtopus cannot run yet", with the path of install.sh to
#     run again;
#   - the PATH line for this shell is printed under Done, not only in step 4;
#   - and `muxtopus` itself refuses to open a session without claude, while
#     one that is only off the calling shell's PATH is found.
#
# SANDBOX: its own HOME, a PATH that holds a fake tmux (so the version is
# ours to choose), --no-watchdog, --no-venv, --no-embedded-python.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxdone-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share"
unset CLAUDE_CONFIG_DIR MUXTOPUS_CONFIG MUXTOPUS_HOME TMUX
export SHELL=/bin/bash
mkdir -p "$HOME" "$SB/fake"
trap '[ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"' EXIT

# A tmux whose version is a parameter, in front of the real one.
fake_tmux() { printf '#!/bin/sh\necho "tmux %s"\n' "$1" > "$SB/fake/tmux"; chmod +x "$SB/fake/tmux"; }
fake_tmux 3.5a
export PATH="$SB/fake:/usr/local/bin:/usr/bin:/bin"

BIN="$HOME/.local/bin"
inst() { "$REPO/install.sh" --no-watchdog --no-venv --no-embedded-python \
           --home "$HOME/muxhome" --bin "$BIN" "$@" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'; }
after_done() { sed -n '/Done/,$p' <<<"$1"; }
reset() { rm -rf "$HOME/.config" "$HOME/muxhome" "$HOME/.local" "$HOME/.profile" "$HOME/.bashrc"; }

echo "== no claude anywhere: a blocker, repeated at the end"
out="$(inst)"
check "step 1 says claude is missing"  grep -q '! claude missing' <<<"$out"
check "the end says it cannot run yet" grep -q '^⚠  Done, but muxtopus cannot run yet:' <<<"$out"
check "and the PATH note is a setup note" grep -q '^⚠  Setup notes:' <<<"$out"
check "and names claude there"         grep -q '● claude is not installed' <<<"$(after_done "$out")"
check "and names install.sh to re-run" grep -qF "Fix that, then run $REPO/install.sh again" <<<"$(after_done "$out")"
check "the PATH line is under Done too" grep -qF 'export PATH="$HOME/.local/bin:$PATH"' <<<"$(after_done "$out")"
check "one command to start with"      grep -q '^Start with:   muxtopus$' <<<"$out"

echo "== claude in ~/.local/bin, off PATH: named, and not a blocker"
reset
mkdir -p "$BIN"; printf '#!/bin/sh\n' > "$BIN/claude"; chmod +x "$BIN/claude"
out="$(inst)"
check "step 1 names where it is"        grep -qF "claude is at $BIN/claude, not on PATH in this shell" <<<"$out"
check "step 1 does not call it missing" bash -c '! grep -q "claude missing" <<<"$1"' _ "$out"
check "the end is a ticked Done"        grep -q '^✅ Done\.$' <<<"$out"
check "no blocker in the notes"         bash -c '! grep -q "● claude\|● tmux" <<<"$1"' _ "$out"
check "nothing said to fix anything"   bash -c '! grep -q "Fix that" <<<"$1"' _ "$out"

echo "== claude on PATH: nothing to say"
out="$(PATH="$BIN:$PATH" inst)"
check "step 1: + claude"                grep -q '+ claude$' <<<"$out"
check "no PATH line for this shell"     bash -c '! grep -q "execute this line first" <<<"$1"' _ "$out"

echo "== tmux 3.0a: a blocker with honest advice"
reset; fake_tmux 3.0a
out="$(PATH="$BIN:$PATH" inst)"
check "step 1 says it is too old"         grep -q 'tmux 3.0a is older than 3.2' <<<"$out"
check "and that the repo may be too"      grep -q "repository is too old" <<<"$out"
check "the end repeats it"                grep -q '● tmux 3.0a is older than 3.2' <<<"$(after_done "$out")"
check "no 'Update it' that reinstalls the same version" bash -c '! grep -q "Update it:" <<<"$1"' _ "$out"

echo "== a dry run ends as before"
reset; fake_tmux 3.5a
out="$(inst --dry-run)"
check "dry run says so and stops"       grep -q '^dry run only' <<<"$out"
check "no Done block"                   bash -c '! grep -q "Done\." <<<"$1"' _ "$out"

echo "== muxtopus refuses to open a session without claude"
reset
# Only the refusal is under test: it comes before any tmux call, so a tmux
# that does nothing is fine, and the sandbox's config keeps it out of the
# real server anyway.
mkdir -p "$XDG_CONFIG_HOME/muxtopus"
printf 'MUXTOPUS_HOME="%s"\nMUXTOPUS_DIR="%s"\n' "$HOME/muxhome" "$REPO" > "$XDG_CONFIG_HOME/muxtopus/config"
out="$("$REPO/muxtopus" 2>&1)"; rc=$?
check "exit 1"                            [ "$rc" = 1 ]
check "says claude is not installed"      grep -q 'claude is not installed' <<<"$out"
# ...but a claude in ~/.local/bin, off this shell's PATH, is NOT refused:
# muxtopus puts that directory on its own PATH first. What comes next is the
# "no account yet" question, which is the check after this one.
mkdir -p "$BIN"; printf '#!/bin/sh\n' > "$BIN/claude"; chmod +x "$BIN/claude"
out="$("$REPO/muxtopus" 2>&1 </dev/null)"
check "off PATH in this shell is fine"    bash -c '! grep -q "claude is not installed" <<<"$1"' _ "$out"
check "it got as far as the account"      grep -q 'there is no account' <<<"$out"

echo
echo "$PASSES passed, $FAILS failed"
[ "$FAILS" = 0 ]
