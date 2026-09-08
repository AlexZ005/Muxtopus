#!/usr/bin/env bash
# install.sh -- put muxtopus on this machine.
#
#   ./install.sh                 install with the defaults
#   ./install.sh --dry-run       print what it would do, touch nothing
#   ./install.sh --home DIR      where schedules/backups/handovers live
#   ./install.sh --bin DIR       where the `mux` link goes (default ~/.local/bin)
#   ./install.sh --also-cc       additionally install it as `cc`
#
# A `cw` is linked too when ~/.claude-work exists: mux reads its own name, so
# `cw` opens the work account the way `cc` opens the default one.
#   ./install.sh --no-watchdog   skip the watchdog service
#
# NOTHING IS WRITTEN OUTSIDE YOUR HOME DIRECTORY, and every path is printed
# before it is touched. There is no curl-pipe-sh here on purpose: this thing
# installs a background daemon that types into your terminals, and that is not
# something anybody should run without having read it first.
set -uo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

DRY=0
BIN="$HOME/.local/bin"
HOME_DIR=""
ALSO_CC=0
WATCHDOG=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY=1; shift ;;
    --home)        [ -n "${2:-}" ] || { echo "--home needs a directory" >&2; exit 2; }
                   HOME_DIR="$2"; shift 2 ;;
    --bin)         [ -n "${2:-}" ] || { echo "--bin needs a directory" >&2; exit 2; }
                   BIN="$2"; shift 2 ;;
    --also-cc)     ALSO_CC=1; shift ;;
    --no-watchdog) WATCHDOG=0; shift ;;
    -h|--help)     sed -n '2,15p' "$0"; exit 0 ;;
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
step "1/5  Checking what is here"
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
# The dashboard prefers a venv beside the checkout (deck-status.sh builds one,
# because a system python can be replaced wholesale by an OS update) and only
# falls back to the system interpreter -- so check both before complaining.
if [ -x "$SRC/.venv/bin/python" ] && "$SRC/.venv/bin/python" -c 'import rich' 2>/dev/null; then
  ok "python rich (dashboard venv)"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import rich' 2>/dev/null; then
  ok "python rich (system)"
else
  warn "python 'rich' missing -- the dashboard falls back to a plain text view"
  warn "  python3 -m venv \"$SRC/.venv\" && \"$SRC/.venv/bin/pip\" install rich"
fi
[ "$missing" = 1 ] && warn "install the missing tools, then run this again to get a clean report"

# ------------------------------------------------------------------ 2. folders
step "2/5  Folders"
run mkdir -p "$HOME_DIR" "$BIN" "$CFG_DIR"
ok "$HOME_DIR"
ok "$BIN"

# ------------------------------------------------------------------- 3. config
step "3/5  Config"
if [ -f "$CFG" ]; then
  skip "$CFG already exists, leaving it alone"
else
  if [ "$DRY" = 1 ]; then
    printf '    \033[90m$ write %s\033[0m\n' "$CFG"
  else
    cat > "$CFG" <<EOF
# Muxtopus -- plain shell, sourced by profile.sh and read by muxconfig.py.
# Anything set here wins over the environment and over the built-in defaults.

# Where an account's schedules/, backups/ and handovers/ live.
MUXTOPUS_HOME="$HOME_DIR"

# This checkout. Needed only when mux is copied rather than symlinked, so it
# cannot find its siblings by following its own path.
MUXTOPUS_DIR="$SRC"
EOF
  fi
  ok "$CFG written"
fi

# ---------------------------------------------------------------- 4. the link
step "4/5  mux"
run chmod +x "$SRC/mux" "$SRC"/*.sh
run ln -sfn "$SRC/mux" "$BIN/mux"
ok "$BIN/mux -> $SRC/mux"
if [ "$ALSO_CC" = 1 ]; then
  # Refuse to shadow a real C compiler. Breaking every native build on the
  # machine is not a reasonable price for two saved keystrokes.
  other="$(command -v cc 2>/dev/null)"
  if [ -n "$other" ] && [ "$other" != "$BIN/cc" ]; then
    warn "not installing 'cc': $other already exists and is probably your C compiler"
  else
    run ln -sfn "$SRC/mux" "$BIN/cc"
    ok "$BIN/cc -> $SRC/mux"
  fi
fi
# One word per account. mux reads the name it was invoked by, so `cw` is
# `mux -w` -- which is what makes an account reachable as an ssh RemoteCommand,
# where there is room for a command and no room for its flags. Only offered
# when the work account actually exists; an alias for nothing is clutter.
if [ -d "$HOME/.claude-work" ]; then
  run ln -sfn "$SRC/mux" "$BIN/cw"
  ok "$BIN/cw -> $SRC/mux  (the work account)"
else
  skip "no ~/.claude-work, so no 'cw' -- create the folder and re-run for it"
fi
case ":$PATH:" in
  *":$BIN:"*) ok "$BIN is on PATH" ;;
  *) warn "$BIN is NOT on PATH -- add it:  export PATH=\"$BIN:\$PATH\"" ;;
esac

# Seed the default account's folders and templates so the first `mux` is not
# also the first time these directories are discovered to be missing.
if [ "$DRY" = 0 ] && command -v python3 >/dev/null 2>&1; then
  MUXTOPUS_HOME="$HOME_DIR" python3 "$SRC/setup-schedules.py" >/dev/null 2>&1 \
    && ok "schedules/, backups/, handovers/ seeded under $HOME_DIR"
fi

# --------------------------------------------------------------- 5. watchdog
step "5/5  Watchdog"
if [ "$WATCHDOG" = 0 ]; then
  skip "skipped (--no-watchdog); bring it up later with: mux"
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
  skip "no systemd --user here; mux will start the daemon in the background instead"
fi

echo
if [ "$DRY" = 1 ]; then
  echo "dry run only -- nothing was written."
else
  echo "Done.  Start with:   mux          (personal account)"
  echo "                     mux -w       (work account, ~/.claude-work)"
  echo "                     mux -l       (what is running)"
fi
