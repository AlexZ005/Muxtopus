#!/usr/bin/env bash
# install.sh puts the bin dir on PATH itself, once, in the right rc files.
#
#   bash tests/test_install_path.sh
#
# A fresh user has no rc file at all (useradd without a skel) and Ubuntu's skel
# ~/.profile only adds ~/.local/bin if it exists at login -- so the first thing
# after every install used to be `export PATH=...` typed by hand. The rule
# under test: the line is appended to ~/.profile AND ~/.bashrc (login shells
# read one, `su user` the other), a FILE that already names the directory is
# left alone, a second install adds no second line, --dry-run and --no-rc write
# nothing, zsh gets ~/.zshrc and fish gets a hint and no file. The decision is
# made per file and never from the current shell's PATH: a directory exported
# by hand to run the installer has nothing behind it, and skipping the rc files
# because of it is how the export ends up being retyped at every login.
#
# SANDBOX: its own HOME, --no-watchdog, --no-venv, --bin inside the sandbox,
# and a PATH that does not contain it.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxpath-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share"
unset CLAUDE_CONFIG_DIR MUXTOPUS_CONFIG MUXTOPUS_HOME TMUX
export PATH="/usr/local/bin:/usr/bin:/bin"
export SHELL=/bin/bash
mkdir -p "$HOME"
trap '[ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"' EXIT

BIN="$HOME/.local/bin"
LINE='export PATH="$HOME/.local/bin:$PATH"'
inst() { "$REPO/install.sh" --no-watchdog --no-venv --home "$HOME/muxhome" --bin "$BIN" "$@"; }
count() { grep -cF "$LINE" "$1" 2>/dev/null || echo 0; }

echo "== a dry run writes no rc file"
out="$(inst --dry-run 2>&1)"
check "dry run names the line" grep -q 'echo .*export PATH' <<<"$out"
check "no ~/.profile" test ! -e "$HOME/.profile"
check "no ~/.bashrc"  test ! -e "$HOME/.bashrc"

echo "== --no-rc only warns"
out="$(inst --no-rc 2>&1)"
check "warns that it is not on PATH" grep -q 'NOT on PATH' <<<"$out"
check "no ~/.profile" test ! -e "$HOME/.profile"
rm -rf "$HOME/.config" "$HOME/muxhome" "$HOME/.local"

echo "== a user with no rc file at all gets both files"
out="$(inst 2>&1)"
check "~/.profile has the line once" test "$(count "$HOME/.profile")" = 1
check "~/.bashrc has the line once"  test "$(count "$HOME/.bashrc")" = 1
check "the line uses \$HOME, not the literal path" bash -c "! grep -qF '$SB' '$HOME/.profile'"
# ...AND PRINTED LAST, under "Done", not in the middle of step 4: the closing
# screenful is the one that gets read (the box that prompted this had the
# line forty rows up and a user who never saw it).
check "the line is printed for the current shell" grep -qF "execute this line first:" <<<"$out"
check "  after Done, not before" bash -c 'sed -n "/Done\./,\$p" <<<"$1" | grep -qF "$2"' _ "$out" "$LINE"

echo "== a second install adds no second line"
inst >/dev/null 2>&1
check "~/.profile still once" test "$(count "$HOME/.profile")" = 1
check "~/.bashrc still once"  test "$(count "$HOME/.bashrc")" = 1

echo "== a file that already names the directory is left alone (Ubuntu's skel)"
rm -rf "$HOME/.config" "$HOME/muxhome" "$HOME/.local" "$HOME/.profile" "$HOME/.bashrc"
printf 'if [ -d "$HOME/.local/bin" ] ; then\n    PATH="$HOME/.local/bin:$PATH"\nfi\n' > "$HOME/.profile"
before="$(cat "$HOME/.profile")"
out="$(inst 2>&1)"
check "~/.profile untouched" test "$(cat "$HOME/.profile")" = "$before"
check "said so" grep -q 'already mentions' <<<"$out"
check "~/.bashrc got it" test "$(count "$HOME/.bashrc")" = 1

# ON PATH IN THIS SHELL IS NOT THE SAME AS ON PATH TOMORROW, and the
# installer no longer confuses the two. It used to skip the rc files whenever
# $BIN was already on PATH, which is wrong exactly when it matters: somebody
# who exported the directory by hand to reach `muxtopus` (or who runs a second
# install in the same shell as the first) has a PATH entry with no file behind
# it, and the old rule wrote nothing and said nothing -- so the export had to
# be retyped at every login. The rc files are now written on their own merits;
# a FILE that already names the directory is still what stops a second line,
# and the block above proves that still holds.
echo "== on PATH by hand, but no file behind it: still persisted"
rm -rf "$HOME/.config" "$HOME/muxhome" "$HOME/.local" "$HOME/.profile" "$HOME/.bashrc"
out="$(PATH="$BIN:$PATH" inst 2>&1)"
check "~/.profile got it" test "$(count "$HOME/.profile")" = 1
check "~/.bashrc got it"  test "$(count "$HOME/.bashrc")" = 1
check "and it does not tell this shell to export what it already has" \
  bash -c '! grep -qF "execute this line first" <<<"$out"'

echo "== on PATH because a file says so: still nothing written twice"
out="$(PATH="$BIN:$PATH" inst 2>&1)"
check "~/.profile still once" test "$(count "$HOME/.profile")" = 1
check "~/.bashrc still once"  test "$(count "$HOME/.bashrc")" = 1
check "said it was already there" grep -q 'already mentions' <<<"$out"

echo "== zsh: ~/.zshrc"
rm -rf "$HOME/.config" "$HOME/muxhome" "$HOME/.local" "$HOME/.profile" "$HOME/.bashrc"
SHELL=/usr/bin/zsh inst >/dev/null 2>&1
check "~/.zshrc has the line" test "$(count "$HOME/.zshrc")" = 1
check "no ~/.profile" test ! -e "$HOME/.profile"

echo "== fish: a hint, no file"
rm -rf "$HOME/.config" "$HOME/muxhome" "$HOME/.local" "$HOME/.zshrc" \
       "$HOME/.profile" "$HOME/.bashrc"
out="$(SHELL=/usr/bin/fish inst 2>&1)"
check "names fish_add_path" grep -q 'fish_add_path' <<<"$out"
check "no ~/.profile" test ! -e "$HOME/.profile"
check "no ~/.config/fish" test ! -e "$HOME/.config/fish"

echo
echo "$PASSES passed, $FAILS failed"
[ "$FAILS" = 0 ]
