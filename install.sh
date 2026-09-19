#!/usr/bin/env bash
# install.sh -- put muxtopus on this machine.
#
#   ./install.sh                 install with the defaults
#   ./install.sh --dry-run       print what it would do, touch nothing
#   ./install.sh --home DIR      where schedules/backups/handovers live
#   ./install.sh --bin DIR       where the `muxtopus` link goes (default ~/.local/bin)
#   ./install.sh --no-watchdog   skip the watchdog service
#   ./install.sh --no-venv       do not build .venv (the dashboard then runs its
#                                plain bash renderer unless python3 has rich)
#   ./install.sh --no-rc         do not add the bin dir to PATH in your shell rc
#
# ONE NAME ON PATH: muxtopus. Not `mux`, which is already several other tools,
# and never `cc`, which on any machine with a C toolchain is the C compiler --
# a `cc` link there breaks every native build. Shorthands belong in your shell
# rc, where they reach an interactive prompt and nothing else; the installer
# prints them. A link named muxtopus-<account> opens that account.
#
# NOTHING IS WRITTEN OUTSIDE YOUR HOME DIRECTORY, and every path is printed
# before it is touched. This script is never piped from the network: it
# installs a background daemon that types into your terminals. get.sh, the
# one-line installer attached to each GitHub release, is the curl-able part,
# and all it does is fetch that release's tarball, check its sha256 against
# the sum baked into it, unpack it and run THIS file from it -- so what runs
# is exactly what that tag is, and it can be read before it is run.
set -uo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# For the config template: one list of keys, defaults and help, shared with
# everything else that writes a config file.
# shellcheck disable=SC1091
. "$SRC/profile.sh"

DRY=0
BIN="$HOME/.local/bin"
HOME_DIR=""
WATCHDOG=1
VENV=1
RC=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY=1; shift ;;
    --home)        [ -n "${2:-}" ] || { echo "--home needs a directory" >&2; exit 2; }
                   HOME_DIR="$2"; shift 2 ;;
    --bin)         [ -n "${2:-}" ] || { echo "--bin needs a directory" >&2; exit 2; }
                   BIN="$2"; shift 2 ;;
    --no-watchdog) WATCHDOG=0; shift ;;
    --no-venv)     VENV=0; shift ;;
    --no-rc)       RC=0; shift ;;
    -h|--help)     sed -n '2,11p' "$0"; exit 0 ;;
    *)             echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/muxtopus"
CFG="$CFG_DIR/config"
DEFAULT_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/muxtopus"

# An existing config is authoritative unless --home overrides it, so re-running
# the installer never silently relocates a working setup.
if [ -z "$HOME_DIR" ] && [ -f "$CFG" ]; then
  HOME_DIR="$(sed -n 's/^MUXTOPUS_HOME=["'"'"']\{0,1\}\(.*[^"'"'"']\)["'"'"']\{0,1\}$/\1/p' "$CFG" | tail -1)"
  HOME_DIR="${HOME_DIR/\$HOME/$HOME}"
  HOME_DIR="${HOME_DIR/\$\{HOME\}/$HOME}"
  [ -n "$HOME_DIR" ] && echo "keeping MUXTOPUS_HOME from $CFG"
fi
HOME_DIR="${HOME_DIR:-$DEFAULT_HOME}"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then printf '    \033[90m$ %s\033[0m\n' "$*"; else "$@"; fi; }

echo "muxtopus installer"
echo "  source     $SRC"
echo "  data home  $HOME_DIR"
echo "  bin        $BIN"
echo "  config     $CFG"
[ "$DRY" = 1 ] && echo "  MODE       dry run, nothing will be written"

# ------------------------------------------------------------- 1. what we need
step "1/6  Checking what is here"
missing=0
for c in bash tmux git; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c"; else warn "$c MISSING (required)"; missing=1; fi
done
for c in jq python3 claude; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c"; else warn "$c missing"; missing=1; fi
done
if command -v tmux >/dev/null 2>&1; then
  tv="$(tmux -V | awk '{print $2}' | tr -d 'a-z')"
  # `new-window -e` is how the account reaches a window; it landed in 3.2.
  awk -v v="$tv" 'BEGIN{exit !(v+0 >= 3.2)}' && ok "tmux $tv" \
    || warn "tmux $tv is older than 3.2 -- per-window env (-e) will not work"
fi
# 3.10: the Python half is written with `X | None`, which 3.9 cannot evaluate.
# Measured, not guessed: the unit tests pass on 3.10 through 3.13 and fail on
# 3.9 at the first import.
if command -v python3 >/dev/null 2>&1; then
  pv="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
  if python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    ok "python $pv"
  else
    warn "python $pv is older than 3.10 -- the dashboard, stats and notifications need 3.10"
    missing=1
  fi
fi
[ "$missing" = 1 ] && warn "install the missing tools, then run this again to get a clean report"

# A config that pins another checkout wins over this one: `muxtopus` reads
# MUXTOPUS_DIR from it and runs THAT code, whatever the link points at. Say so,
# rather than let an upgrade quietly keep running the old tree.
if [ -f "$CFG" ]; then
  pinned="$(sed -n 's/^MUXTOPUS_DIR=["'"'"']\{0,1\}\(.*[^"'"'"']\)["'"'"']\{0,1\}$/\1/p' "$CFG" | tail -1)"
  pinned="${pinned/\$HOME/$HOME}"
  if [ -n "$pinned" ] && [ "$(cd "$pinned" 2>/dev/null && pwd -P)" != "$SRC" ]; then
    warn "$CFG pins MUXTOPUS_DIR=$pinned, so muxtopus will keep running THAT code"
    warn "  to run this one, set MUXTOPUS_DIR=$SRC there (or delete the line)"
  fi
fi

# ------------------------------------------------------------------ 2. folders
step "2/6  Folders"
run mkdir -p "$HOME_DIR" "$BIN" "$CFG_DIR/profiles"
ok "$HOME_DIR"
ok "$BIN"

# ------------------------------------------------------------------- 3. config
step "3/6  Config"
if [ -f "$CFG" ]; then
  skip "$CFG already exists, leaving it alone"
else
  if [ "$DRY" = 1 ]; then
    printf '    \033[90m$ write %s\033[0m\n' "$CFG"
  else
    # Every key, commented at its default, plus the two this install pins.
    mux_config_template "" "MUXTOPUS_HOME=$HOME_DIR" "MUXTOPUS_DIR=$SRC" > "$CFG"
  fi
  ok "$CFG written"
fi

# options.md -- the schedule-options checkbox table, read by the dashboard from
# beside the config file (muxconfig.options_paths), NOT from MUXTOPUS_HOME.
# ONLY IF MISSING, and never rewritten: the sentences in it are the user's own
# contract with their lanes, and an installer that "updates" them would silently
# retract whatever they had edited. A new option in a later release is a line in
# the release notes, not an overwrite.
OPTS="$CFG_DIR/options.md"
if [ -f "$OPTS" ]; then
  skip "$OPTS already exists, leaving it alone"
elif [ ! -f "$SRC/seeds/options.md" ]; then
  warn "no seeds/options.md in $SRC -- the table will open empty until you write one"
elif [ "$DRY" = 1 ]; then
  printf '    \033[90m$ cp %s %s\033[0m\n' "$SRC/seeds/options.md" "$OPTS"
else
  cp "$SRC/seeds/options.md" "$OPTS"
  ok "$OPTS seeded ($(grep -c '^key: ' "$OPTS") options)"
fi

# prices.md -- the price and model table behind the insights view's $ figures
# and its "% of the context window". Beside the config file for the same reason
# options.md is, and ONLY IF MISSING for the same reason too: the numbers in it
# go out of date, the user is the one who updates them, and an installer that
# "refreshed" them would throw away an edit with no way to get it back. A price
# change in a later release is a line in the release notes.
PRICES="$CFG_DIR/prices.md"
if [ -f "$PRICES" ]; then
  skip "$PRICES already exists, leaving it alone"
elif [ ! -f "$SRC/seeds/prices.md" ]; then
  warn "no seeds/prices.md in $SRC -- insights will show tokens and no \$ figures"
elif [ "$DRY" = 1 ]; then
  printf '    \033[90m$ cp %s %s\033[0m\n' "$SRC/seeds/prices.md" "$PRICES"
else
  cp "$SRC/seeds/prices.md" "$PRICES"
  ok "$PRICES seeded ($(grep -c '^model: ' "$PRICES") models, $(sed -n 's/^as of: //p' "$PRICES" | head -1))"
fi

# ---------------------------------------------------------------- 4. the link
step "4/6  muxtopus"
run chmod +x "$SRC/muxtopus" "$SRC"/*.sh
run ln -sfn "$SRC/muxtopus" "$BIN/muxtopus"
ok "$BIN/muxtopus -> $SRC/muxtopus"
# Links an earlier version made under the old names would now dangle -- or,
# for `cc`, keep working under a name that shadows the C compiler. Only OUR
# links go: one pointing anywhere else is somebody else's program.
for old in mux cc cw; do
  case "$(readlink "$BIN/$old" 2>/dev/null)" in
    "$SRC/mux"|"$SRC/muxtopus") run rm -f "$BIN/$old"; ok "removed the old link $BIN/$old" ;;
  esac
done
# ~/.local/bin IS NOT ON PATH ON EVERY MACHINE. Ubuntu's stock ~/.profile adds
# it only if it exists at login, a user made with `useradd` and no skel has no
# rc file at all, and a container has whatever its image had. Saying "add it"
# and stopping made the first thing after every install a line to paste
# (measured: a fresh Ubuntu 25.04 user), so the line goes into the shell rc
# here, once, behind a marker. TWO FILES FOR BASH, because `ssh user@host` is
# a login shell that reads ~/.profile and `su user` an interactive one that
# reads only ~/.bashrc; a file that already names the directory (Ubuntu's
# skel does) is left alone, since the next login picks it up. fish is not sh
# and gets the line to type. The current shell cannot be changed from here --
# least of all through `curl | bash` -- so the line is printed for it too.
# This is the one write outside ~/.config and ~/.local; --no-rc skips it.
path_into_rc() {
  local short="$BIN" tilde="$BIN" line f
  case "$BIN" in
    "$HOME"/*) short="\$HOME${BIN#"$HOME"}"; tilde="~${BIN#"$HOME"}" ;;
  esac
  line="export PATH=\"$short:\$PATH\""
  local files=()
  case "$(basename -- "${SHELL:-sh}")" in
    fish) warn "$BIN is NOT on PATH; for fish:  fish_add_path $BIN"; return 0 ;;
    zsh)  files=("$HOME/.zshrc") ;;
    *)    files=("$HOME/.profile" "$HOME/.bashrc") ;;
  esac
  for f in "${files[@]}"; do
    if [ -f "$f" ] && grep -Fq -e "$BIN" -e "$short" -e "$tilde" "$f"; then
      skip "$f already mentions $BIN"
    elif [ "$DRY" = 1 ]; then
      printf '    \033[90m$ echo %s >> %s\033[0m\n' "'$line'" "$f"
    else
      printf '\n# muxtopus (install.sh): the muxtopus link lives here\n%s\n' "$line" >> "$f"
      ok "$f: $line"
    fi
  done
  warn "PATH changes at your next login; for this shell:  $line"
}
case ":$PATH:" in
  *":$BIN:"*) ok "$BIN is on PATH" ;;
  *) if [ "$RC" = 1 ]; then path_into_rc
     else warn "$BIN is NOT on PATH -- add it:  export PATH=\"$BIN:\$PATH\""; fi ;;
esac
echo "    shorthands, if you want them, go in your shell rc (interactive only):"
echo "      alias cc='muxtopus'"
echo "      alias cw='muxtopus --profile=work'"

# Seed the default account's folders and templates so the first `muxtopus` is not
# also the first time these directories are discovered to be missing.
if [ "$DRY" = 0 ] && command -v python3 >/dev/null 2>&1; then
  MUXTOPUS_HOME="$HOME_DIR" python3 "$SRC/setup-schedules.py" >/dev/null 2>&1 \
    && ok "schedules/, backups/, handovers/ seeded under $HOME_DIR"
fi

# ------------------------------------------------------- 5. dashboard runtime
# The dashboard is Rich when $SRC/.venv/bin/python can import rich, and a plain
# bash renderer otherwise (deck-status.sh). A venv beside the code, not a
# system package: an OS update that replaces python3 breaks a venv, which
# after-update.sh rebuilds, but it never breaks the fallback -- the dashboard
# is what you open when something is broken. 27 MB, one pip download.
step "5/6  Dashboard runtime"
if [ "$VENV" = 0 ]; then
  skip "skipped (--no-venv)"
elif [ -x "$SRC/.venv/bin/python" ] && "$SRC/.venv/bin/python" -c 'import rich' 2>/dev/null; then
  skip "$SRC/.venv already has rich"
elif ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  warn "no python3 >= 3.10 -- the dashboard will use its plain bash renderer"
elif [ "$DRY" = 1 ]; then
  printf '    \033[90m$ python3 -m venv %s && %s install rich\033[0m\n' "$SRC/.venv" "$SRC/.venv/bin/pip"
elif python3 -m venv "$SRC/.venv" >/dev/null 2>&1 \
     && "$SRC/.venv/bin/pip" install --quiet --disable-pip-version-check rich >/dev/null 2>&1; then
  ok "$SRC/.venv with rich $("$SRC/.venv/bin/python" -c 'import importlib.metadata as m; print(m.version("rich"))')"
else
  warn "could not build $SRC/.venv (no network, or no python3-venv?) -- plain renderer until:"
  warn "  python3 -m venv \"$SRC/.venv\" && \"$SRC/.venv/bin/pip\" install rich"
fi

# --------------------------------------------------------------- 6. watchdog
step "6/6  Watchdog"
if [ "$WATCHDOG" = 0 ]; then
  skip "skipped (--no-watchdog); bring it up later with: muxtopus"
elif [ "$DRY" = 1 ]; then
  printf '    \033[90m$ %s --install\033[0m\n' "$SRC/claude-watchdog.sh"
elif command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  if "$SRC/claude-watchdog.sh" --install >/dev/null 2>&1; then
    ok "installed and started (systemd --user)"
    if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
      warn "lingering is OFF, so it dies at logout: sudo loginctl enable-linger $USER"
    fi
  else
    warn "install failed; try: $SRC/claude-watchdog.sh --install"
  fi
else
  skip "no systemd --user here; muxtopus will start the daemon in the background instead"
fi

echo
if [ "$DRY" = 1 ]; then
  echo "dry run only -- nothing was written."
else
  echo "Done.  Start with:   muxtopus                  (personal account)"
  echo "                     muxtopus --profile=work   (work account, ~/.claude-work)"
  echo "                     muxtopus -l               (what is running)"
fi
