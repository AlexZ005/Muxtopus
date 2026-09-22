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
#   ./install.sh --no-embedded-python
#                                do not fetch a python when this machine has no
#                                python3 >= 3.10; nothing is downloaded
#   ./install.sh --no-rc         do not add the bin dir to PATH in your shell rc
#
# ONE NAME ON PATH: muxtopus. Not `mux`, which is already several other tools,
# and never `cc`, which on any machine with a C toolchain is the C compiler --
# a `cc` link there breaks every native build. Shorthands belong in your shell
# rc, where they reach an interactive prompt and nothing else; docs/install.md
# shows them. A link named muxtopus-<account> opens that account.
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
EMBED=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY=1; shift ;;
    --home)        [ -n "${2:-}" ] || { echo "--home needs a directory" >&2; exit 2; }
                   HOME_DIR="$2"; shift 2 ;;
    --bin)         [ -n "${2:-}" ] || { echo "--bin needs a directory" >&2; exit 2; }
                   BIN="$2"; shift 2 ;;
    --no-watchdog) WATCHDOG=0; shift ;;
    --no-venv)     VENV=0; shift ;;
    --no-embedded-python) EMBED=0; shift ;;
    --no-rc)       RC=0; shift ;;
    -h|--help)     sed -n '2,14p' "$0"; exit 0 ;;
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
# ONE LINE PER TOOL, and the version is part of the line. This used to report
# the tool and then report it AGAIN from a second check below -- `+ tmux`,
# then `+ tmux 3.5`; `+ python3`, then `+ python 3.13` -- which reads as two
# findings about two different things, and buries the one line that matters
# (the version being too old) under a duplicate of the one that does not.
step "1/7  Checking what is here"
missing=0
# WHAT STOPS MUXTOPUS FROM RUNNING, kept for the last thing printed. This
# step is the first of seven; its warnings are forty lines up by the time the
# closing "Done" is on screen, and "Done. Start with: muxtopus" was read as
# exactly that on a box whose tmux was too old and whose `claude` was not on
# PATH (measured: Ubuntu 20.04, where `muxtopus` then opened a window that
# said "claude: command not found" and sat at a bare prompt). Each one is a
# line the user can act on, and the closing block repeats them.
BLOCKERS=()
blocker() { BLOCKERS+=("$*"); }

# THE PACKAGE IS NOT ALWAYS THE COMMAND. `sudo pacman -S python3` fails on
# Arch (the package is `python`), and `claude` is not in any distro at all --
# both were printed by the first version of this, in a container, which is
# where package names get checked. A tool with no package gets its own line.
pkg_line() {   # how you would install $1 on THIS machine
  local p="$1"
  if [ "$p" = claude ]; then
    echo "https://docs.claude.com/en/docs/claude-code -- not a distro package"
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    # Debian and Ubuntu split the venv module out, and the dashboard's venv
    # is what step 6 builds.
    [ "$p" = python3 ] && p="python3 python3-venv"
    echo "sudo apt install $p"
  elif command -v dnf >/dev/null 2>&1;     then echo "sudo dnf install $p"
  elif command -v pacman >/dev/null 2>&1; then
    # Arch calls it `python`, and has had no `python3` package for years.
    [ "$p" = python3 ] && p="python"
    echo "sudo pacman -S $p"
  elif command -v brew >/dev/null 2>&1; then
    [ "$p" = python3 ] && p="python"
    echo "brew install $p"
  elif command -v zypper >/dev/null 2>&1;  then echo "sudo zypper install $p"
  elif command -v apk >/dev/null 2>&1;     then echo "sudo apk add $p"
  else echo "install $p with your package manager"; fi
}

# The version each tool reports, in ONE word. `claude` is not asked: it is a
# Node program whose --version can take a second, and an installer that hangs
# on a version string it only wanted to print is a bad trade.
tool_version() {
  case "$1" in
    bash)    printf '%s' "${BASH_VERSION%%[-(]*}" ;;
    tmux)    tmux -V 2>/dev/null | awk '{print $2}' ;;
    git)     git --version 2>/dev/null | awk '{print $3}' ;;
    jq)      jq --version 2>/dev/null | sed 's/^jq-//' ;;
    python3) python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null ;;
  esac
}

# WHERE `claude` IS WHEN IT IS NOT ON PATH. Its own installer puts it in
# ~/.local/bin and, like this one, cannot change the shell it was run from --
# so on the machine that prompted this, `claude` was installed, in the very
# directory step 4 puts on PATH, and this reported it missing and sent the
# user to the docs to install it again. A binary that is there is named, with
# the one thing that is actually wrong.
claude_off_path() {   # prints the path of a claude that PATH cannot see
  local d
  for d in "$BIN" "$HOME/.local/bin"; do
    if [ -x "$d/claude" ]; then echo "$d/claude"; return 0; fi
  done
  return 1
}

for c in bash tmux git jq python3 claude; do
  v="$(tool_version "$c")"
  if ! command -v "$c" >/dev/null 2>&1; then
    case "$c" in
      bash|tmux|git) warn "$c MISSING (required) -- $(pkg_line "$c")"; missing=1
                     blocker "$c is not installed: $(pkg_line "$c")" ;;
      python3)       warn "python3 missing -- $(pkg_line python3), or let step 5 fetch one" ;;
      claude)
        # A NOTE, NOT A BLOCKER, either way: step 4 puts $BIN on PATH, and
        # `muxtopus` puts ~/.local/bin in front of its own PATH before it
        # runs anything, so a claude in either place is found from the
        # first `muxtopus` on.
        if cp="$(claude_off_path)"; then
          skip "claude is at $cp, not on PATH in this shell -- muxtopus will find it there"
        else
          warn "claude missing -- $(pkg_line claude)"; missing=1
          blocker "claude is not installed: $(pkg_line claude)"
        fi ;;
      # jq IS OPTIONAL NOW, and this line is the whole reason it can
      # be: muxjson.py stands in for it (profile.sh, mux_json). It used to be
      # listed with the required tools, warned about once and then never
      # mentioned again -- while the watchdog quietly could not read
      # sessions/<pid>.json and reported "0 session(s)" for it. Say what is
      # slower now rather than what is broken, because nothing is.
      jq)            skip "jq missing -- muxtopus uses its own reader instead;"
                     skip "  install it for a faster one: $(pkg_line jq)" ;;
      *)             warn "$c missing -- $(pkg_line "$c")"; missing=1 ;;
    esac
    continue
  fi
  case "$c" in
    tmux)
      # `new-window -e` is how the account reaches a window; it landed in 3.2.
      # THE VERSION IS WORTH SAYING EVEN WHEN IT IS FINE: it is the one
      # dependency whose age silently removes a feature rather than failing.
      tv="$(printf '%s' "$v" | tr -d 'a-z')"
      if awk -v n="$tv" 'BEGIN{exit !(n+0 >= 3.2)}'; then
        ok "tmux $v"
      else
        # "sudo apt install tmux" IS THE WRONG ADVICE on the machine most
        # likely to be reading it: Ubuntu 20.04's repository has 3.0a, so
        # the command it printed reinstalled the version it had just
        # complained about. Say what the package manager can do and what
        # it cannot, rather than a line that looks like a fix and is not.
        warn "tmux $v is older than 3.2 -- per-window env (-e) will not work,"
        warn "  so a window cannot be given its own account. Try: $(pkg_line tmux)"
        warn "  If that leaves it at $v, your distro's repository is too old (3.2 is in"
        warn "  Ubuntu 22.04 and Debian 12); a newer tmux has to come from elsewhere."
        missing=1
        blocker "tmux $v is older than 3.2: $(pkg_line tmux), or a newer one from outside your distro"
      fi
      ;;
    python3)
      # 3.10: the Python half is written with `X | None`, which 3.9 cannot
      # evaluate. Measured, not guessed: the unit tests pass on 3.10 through
      # 3.13 and fail on 3.9 at the first import.
      if python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        ok "python3 $v"
        SYS_PY_OK=1
      else
        warn "python3 $v is older than 3.10 -- the dashboard, stats and"
        warn "  notifications need 3.10; step 5 fetches one rather than stop here"
      fi
      ;;
    claude) ok "claude" ;;
    *)      ok "$c${v:+ $v}" ;;
  esac
done
[ "$missing" = 1 ] && warn "install the missing tools, then run $SRC/install.sh again for a clean report"

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
step "2/7  Folders"
run mkdir -p "$HOME_DIR" "$BIN" "$CFG_DIR/profiles"
ok "$HOME_DIR"
ok "$BIN"

# ------------------------------------------------------------------- 3. config
step "3/7  Config"
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
step "4/7  muxtopus"
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
# THE LINE ITSELF IS COMPUTED ONCE, HERE, because two places print it: the
# rc files below, and the closing block, which repeats it for the shell the
# installer was run from. `$HOME` rather than the literal path, so the same
# line is right in a dotfile that travels between machines.
PATH_SHORT="$BIN" PATH_TILDE="$BIN"
case "$BIN" in
  "$HOME"/*) PATH_SHORT="\$HOME${BIN#"$HOME"}"; PATH_TILDE="~${BIN#"$HOME"}" ;;
esac
PATH_LINE="export PATH=\"$PATH_SHORT:\$PATH\""
case "$(basename -- "${SHELL:-sh}")" in
  fish) PATH_LINE="fish_add_path $BIN" ;;
esac
# Whether THIS shell can see $BIN, decided once, before anything below
# could change the answer.
ON_PATH_NOW=0
case ":$PATH:" in *":$BIN:"*) ON_PATH_NOW=1 ;; esac

path_into_rc() {
  local f
  local files=()
  case "$(basename -- "${SHELL:-sh}")" in
    fish) warn "$BIN is NOT on PATH; for fish:  $PATH_LINE"; return 0 ;;
    zsh)  files=("$HOME/.zshrc") ;;
    *)    files=("$HOME/.profile" "$HOME/.bashrc") ;;
  esac
  for f in "${files[@]}"; do
    if [ -f "$f" ] && grep -Fq -e "$BIN" -e "$PATH_SHORT" -e "$PATH_TILDE" "$f"; then
      skip "$f already mentions $BIN"
    elif [ "$DRY" = 1 ]; then
      printf '    \033[90m$ echo %s >> %s\033[0m\n' "'$PATH_LINE'" "$f"
    else
      printf '\n# muxtopus (install.sh): the muxtopus link lives here\n%s\n' "$PATH_LINE" >> "$f"
      ok "$f: $PATH_LINE"
    fi
  done
  # The line for THIS shell is printed at the very end, beside "Start
  # with", not here: here it was the middle of step 4 of 7 and off the
  # screen by the time the user reached the command it was needed for.
}

# WRITE THE RC LINE ON ITS OWN MERITS, not on what THIS shell's PATH happens
# to say. It used to ask "is $BIN on PATH?" first and do nothing if it was,
# which has one bad case and it is the common one: export the directory by
# hand to get at `muxtopus`, or run a second install in the same shell as the
# first, and the installer sees a PATH that already has it, writes nothing and
# says nothing -- so the export has to be typed again at every login, forever.
# A PATH entry with no file behind it lasts until the shell closes.
#
# path_into_rc is the right thing to ask instead, because it already decides
# per FILE: one that names the directory (Ubuntu's skel ~/.profile does) is
# left alone and said so, and one that does not gets the line, once, behind a
# marker. So calling it unconditionally writes nothing new on a machine that
# was already set up and fixes the machine that only looked as though it was.
if [ "$RC" = 1 ]; then
  path_into_rc
elif [ "$ON_PATH_NOW" = 1 ]; then
  ok "$BIN is on PATH"
else
  warn "$BIN is NOT on PATH -- add it:  $PATH_LINE"
fi
# The alias suggestions that used to be printed here (cc, cw) are in
# docs/install.md: a first install has one account and one command to learn.

# --------------------------------------------------------------- 5. python
# THE PYTHON HALF HAS A FLOOR OF 3.10 and a machine is allowed not to meet it.
# Debian 11, Ubuntu 20.04 and a plain container all ship 3.9 or nothing, and
# the answer used to be a warning and a dashboard with no colours, no stats,
# no notifications and no schedules view -- most of the program, withheld for
# a reason the user cannot fix without root.
#
# So it fetches one: a standalone CPython from astral-sh/python-build-standalone
# (the same builds `uv` installs), unpacked into the data home.
#
# IT IS MUXTOPUS'S PYTHON, NOT THE MACHINE'S. Nothing is linked into ~/.local/bin,
# nothing is put on PATH, no system package is touched and no other program can
# reach it by accident: the only thing that ever runs it is muxtopus, through
# MUX_PYTHON (profile.sh), and it is one directory to delete. An installer that
# put a python3 of its own choosing in front of the user's tools would be
# fixing its own problem with somebody else's environment.
#
# IT IS CHECKED. The release publishes a .sha256 beside every asset; the
# tarball is refused if the two disagree. Both come over TLS from the same
# release, so this catches a corrupted download and a swapped asset -- not a
# compromised account, and this says so rather than implying more.
PY_DIR="$HOME_DIR/python"
# The release to read the asset list from. An env var only so that
# tests/test_install_python.sh can serve a release of its own over file:// and
# drive this whole path offline -- the download, the sha256 gate and the
# refusal -- rather than leave the one step that touches the network as the
# one step nothing checks.
PBS_API="${MUXTOPUS_PBS_API:-https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest}"

embedded_python() {
  local arch os url name want got tmp
  case "$(uname -s)" in
    Linux) os="unknown-linux-gnu" ;;
    *) warn "no standalone build for $(uname -s) -- install python3 >= 3.10 yourself"; return 1 ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64)  arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
    *) warn "no standalone build for $(uname -m) -- install python3 >= 3.10 yourself"; return 1 ;;
  esac
  command -v curl >/dev/null 2>&1 || { warn "curl is needed to fetch python -- $(pkg_line curl)"; return 1; }
  command -v tar  >/dev/null 2>&1 || { warn "tar is needed to unpack python -- $(pkg_line tar)"; return 1; }
  command -v sha256sum >/dev/null 2>&1 || { warn "sha256sum is needed to check it -- $(pkg_line coreutils)"; return 1; }

  # THE NEWEST RELEASED 3.x INSTALL-ONLY BUILD for this machine, from the
  # release's own asset list. Parsed with grep rather than jq, which is one of
  # the tools this script is quite prepared to find missing.
  #
  # TWO KINDS OF ASSET ARE REFUSED HERE and both were found by installing this
  # in a container rather than by reading the list:
  #
  #   a PRE-RELEASE. The names carry the python version, and `3.15.0rc2` sorts
  #   above `3.14.7` -- so the newest build in the list was a release
  #   candidate, and a machine with no python3 would have been handed one. The
  #   `%2B` in the pattern is what enforces it: it is the `+` that separates
  #   the version from the build date, so a version with `rc` in it does not
  #   reach it. (The API spells that plus as %2B.)
  #
  #   a FREE-THREADED build, which is a different runtime with a different
  #   performance profile, offered beside the ordinary one under a name that
  #   sorts identically. Nothing here asks for one.
  url="$(curl -fsSL --max-time 30 "$PBS_API" 2>/dev/null \
         | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4 \
         | grep -- "-${arch}-${os}-install_only\.tar\.gz$" \
         | grep -v -- "-freethreaded-" \
         | grep -E "/cpython-3\.[0-9]+\.[0-9]+(%2B|\+)" \
         | sed 's|.*/cpython-\([0-9][0-9.]*\)\(%2B\|+\).*|\1 &|' \
         | sort -V | tail -1 | cut -d' ' -f2-)"
  if [ -z "$url" ]; then
    warn "could not reach $PBS_API -- no network? install python3 >= 3.10 instead"
    return 1
  fi
  ok "fetching $(basename "$url")"
  skip "$url"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/muxpy-XXXXXX")" || return 1
  if ! curl -fsSL --max-time 600 -o "$tmp/py.tar.gz" "$url"; then
    warn "download failed"; rm -rf -- "${tmp:?}"; return 1
  fi
  # THE SUMS ARE ONE FILE FOR THE WHOLE RELEASE -- `SHA256SUMS` beside the
  # assets, `<sum>  <name>` a line -- and NOT a `.sha256` per asset, which is
  # what this asked for first and what a container install proved does not
  # exist: every download was refused and every machine fell back to the bash
  # renderer, silently doing the old thing. The name in that file carries a
  # literal `+` where the URL has `%2B`.
  name="$(basename "$url")"
  name="${name//%2B/+}"
  want="$(curl -fsSL --max-time 60 "${url%/*}/SHA256SUMS" 2>/dev/null \
          | awk -v n="$name" '$2 == n {print $1; exit}')"
  got="$(sha256sum "$tmp/py.tar.gz" | cut -d' ' -f1)"
  if [ -z "$want" ]; then
    warn "no published sha256 for $name -- refusing to unpack it"
    rm -rf -- "${tmp:?}"; return 1
  fi
  if [ "$want" != "$got" ]; then
    warn "sha256 MISMATCH -- refusing to unpack"
    warn "  published $want"
    warn "  downloaded $got"
    rm -rf -- "${tmp:?}"; return 1
  fi
  ok "sha256 matches the published sum"
  # The archive holds a single `python/` directory, so it unpacks INTO the
  # data home and becomes $PY_DIR. A previous one is moved aside rather than
  # deleted under a running dashboard.
  if [ -d "$PY_DIR" ]; then
    rm -rf -- "${PY_DIR:?}.old"
    mv -- "${PY_DIR:?}" "${PY_DIR:?}.old"
  fi
  if ! tar -xzf "$tmp/py.tar.gz" -C "$HOME_DIR"; then
    warn "could not unpack it"
    # PUT THE OLD ONE BACK. A half-unpacked archive must not cost a machine
    # the interpreter it was already running on.
    rm -rf -- "${PY_DIR:?}"
    [ -d "${PY_DIR:?}.old" ] && mv -- "${PY_DIR:?}.old" "${PY_DIR:?}"
    rm -rf -- "${tmp:?}"
    return 1
  fi
  rm -rf -- "${tmp:?}" "${PY_DIR:?}.old"
  if ! "$PY_DIR/bin/python3" -c 'import sys, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    warn "the fetched python does not run here -- leaving it at $PY_DIR"
    return 1
  fi
  ok "$PY_DIR/bin/python3 ($("$PY_DIR/bin/python3" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"
  skip "muxtopus only; nothing was added to PATH"
  return 0
}

step "5/7  Python"
PY="python3"
if [ "${SYS_PY_OK:-0}" = 1 ]; then
  skip "python3 $(tool_version python3) is what muxtopus will use"
elif [ "$EMBED" = 0 ]; then
  warn "no python3 >= 3.10 and --no-embedded-python -- the dashboard will use"
  warn "  its plain bash renderer, and stats and notifications will not run"
elif [ -x "$PY_DIR/bin/python3" ] \
     && "$PY_DIR/bin/python3" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  PY="$PY_DIR/bin/python3"
  skip "$PY is already here"
elif [ "$DRY" = 1 ]; then
  printf '    \033[90m$ fetch a standalone CPython into %s\033[0m\n' "$PY_DIR"
elif embedded_python; then
  PY="$PY_DIR/bin/python3"
else
  warn "carrying on without it -- the dashboard will use its plain bash renderer"
fi
# WRITTEN DOWN, so every later run agrees with this one. The config is only
# ever added to here: a MUXTOPUS_PYTHON already in it is the user's own answer.
if [ "$PY" != "python3" ] && [ "$DRY" = 0 ] && [ -f "$CFG" ] \
   && ! grep -q '^MUXTOPUS_PYTHON=' "$CFG"; then
  printf '\n# muxtopus (install.sh): the interpreter fetched for the python half\nMUXTOPUS_PYTHON="%s"\n' \
         "$PY" >> "$CFG"
  ok "$CFG: MUXTOPUS_PYTHON=$PY"
fi

# Seed the default account's folders and templates so the first `muxtopus` is
# not also the first time these directories are discovered to be missing.
#
# AFTER THE PYTHON STEP, WITH ITS PYTHON, AND NEVER SILENTLY. This ran in step
# 4 with the system python3 and sent everything to /dev/null: on a box whose
# python3 was 3.8 (Ubuntu 20.04) the import failed, nothing was seeded, and
# nothing said so -- the "seeded" line was simply absent from a transcript
# that ended in "Done". Step 5 exists to fetch a python that can run this.
if [ "$DRY" = 1 ]; then
  printf '    \033[90m$ %s %s/setup-schedules.py\033[0m\n' "$PY" "$SRC"
elif ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  warn "no python3 >= 3.10, so schedules/, backups/, handovers/ are not seeded;"
  warn "  muxtopus makes them on first run"
elif MUXTOPUS_HOME="$HOME_DIR" "$PY" "$SRC/setup-schedules.py" >/dev/null 2>&1; then
  ok "schedules/, backups/, handovers/ seeded under $HOME_DIR"
else
  warn "could not seed schedules/, backups/, handovers/ under $HOME_DIR; by hand:"
  warn "  MUXTOPUS_HOME=\"$HOME_DIR\" $PY $SRC/setup-schedules.py"
fi

# ------------------------------------------------------- 6. dashboard runtime
# The dashboard is Rich when $SRC/.venv/bin/python can import rich, and a plain
# bash renderer otherwise (deck-status.sh). A venv beside the code, not a
# system package: an OS update that replaces python3 breaks a venv, which
# after-update.sh rebuilds, but it never breaks the fallback -- the dashboard
# is what you open when something is broken. 27 MB, one pip download.
#
# BUILT FROM $PY, which is the system python3 when it is new enough and the
# fetched one when it is not -- so a machine with no usable python3 gets the
# Rich dashboard too, and after-update.sh's rebuild finds the same interpreter
# through MUX_PYTHON.
step "6/7  Dashboard runtime"
if [ "$VENV" = 0 ]; then
  skip "skipped (--no-venv)"
elif [ -x "$SRC/.venv/bin/python" ] && "$SRC/.venv/bin/python" -c 'import rich' 2>/dev/null; then
  skip "$SRC/.venv already has rich"
elif ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  warn "no python3 >= 3.10 -- the dashboard will use its plain bash renderer"
elif [ "$DRY" = 1 ]; then
  printf '    \033[90m$ %s -m venv %s && %s install rich\033[0m\n' "$PY" "$SRC/.venv" "$SRC/.venv/bin/pip"
elif "$PY" -m venv "$SRC/.venv" >/dev/null 2>&1 \
     && "$SRC/.venv/bin/pip" install --quiet --disable-pip-version-check rich >/dev/null 2>&1; then
  ok "$SRC/.venv with rich $("$SRC/.venv/bin/python" -c 'import importlib.metadata as m; print(m.version("rich"))')"
else
  warn "could not build $SRC/.venv (no network, or no python3-venv?) -- plain renderer until:"
  warn "  $PY -m venv \"$SRC/.venv\" && \"$SRC/.venv/bin/pip\" install rich"
fi

# --------------------------------------------------------------- 7. watchdog
step "7/7  Watchdog"
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

# ------------------------------------------------------------------ the end
# THE LAST SCREENFUL IS THE ONE THAT IS READ, so it carries the two things a
# user has to act on: what step 1 found that stops muxtopus running, and the
# PATH line for the shell they are sitting in. Both used to be printed where
# they were discovered, forty lines up, and "Done. Start with: muxtopus" was
# taken at its word on a machine where it was not true. The shape follows
# what rustup, uv and Claude Code's own installer print: restart the shell,
# or paste this one line now.
#
# ONE COMMAND TO START WITH. A first install has one account; the second
# account, named sessions and `-l` are one `muxtopus -h` away, and three
# commands under "Start with" read as three things to do.
echo
if [ "$DRY" = 1 ]; then
  echo "dry run only -- nothing was written."
  exit 0
fi
# THE SHAPE IS CLAUDE CODE'S OWN INSTALLER'S: a "Setup notes" block with a
# warning sign, one sentence on what is wrong and the exact line to run,
# because that is what the same user has just read for `claude` and it is
# what the next line of their terminal history will look like.
echo "Done."
if [ "${#BLOCKERS[@]}" -gt 0 ] || [ "$ON_PATH_NOW" = 0 ]; then
  echo
  echo "⚠  Setup notes:"
  for b in "${BLOCKERS[@]}"; do
    echo "  ● $b"
  done
  [ "${#BLOCKERS[@]}" -gt 0 ] && echo "    Fix that, then run $SRC/install.sh again for a clean report."
  if [ "$ON_PATH_NOW" = 0 ]; then
    if [ "$RC" = 1 ]; then
      echo "  ● $PATH_TILDE is not on PATH in this shell (new shells will have it). To run"
      echo "    muxtopus now, execute this line first:"
    else
      echo "  ● $PATH_TILDE is not on PATH (--no-rc left your shell rc alone). To run"
      echo "    muxtopus, execute this line first:"
    fi
    echo
    echo "    $PATH_LINE"
  fi
fi
echo
echo "Start with:   muxtopus"
echo "More:         muxtopus -h   (a second account, named sessions, what is running)"
