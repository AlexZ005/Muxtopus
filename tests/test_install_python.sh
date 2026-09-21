#!/usr/bin/env bash
# install.sh: the report says each tool once, and a machine with no usable
# python3 gets one fetched for it.
#
#   bash tests/test_install_python.sh
#
# WHY THE DOWNLOAD IS TESTED AND NOT MOCKED AWAY. Fetching an interpreter is
# the one thing this installer does that reaches the network, unpacks an
# archive and then RUNS what came out of it, so "it worked on the machine I
# wrote it on" is not good enough: the sha256 gate in particular is code that
# only ever runs when something is wrong, which is the code most likely to be
# wrong itself. So this builds a release of its own -- an asset list, a
# tarball, and the .sha256 beside it -- serves it over file:// through
# MUXTOPUS_PBS_API, and drives the real path: the happy one, the one where the
# sum does not match, and the one where the user said not to.
#
# THE FETCHED PYTHON IS A STUB that execs the real python3. What is under test
# is the installer's handling of it -- checked, unpacked, probed, written into
# the config, used to build the venv -- and not CPython, which needs no test
# from us and would make this a 30 MB download.
#
# SANDBOX: its own HOME, its own PATH with a python3 that lies about its
# version, --no-watchdog and --no-rc. Nothing here reaches the real network,
# the real config or the real data home.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxpy-XXXXXX")"
REAL_PY="$(command -v python3)"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share"
unset CLAUDE_CONFIG_DIR MUXTOPUS_CONFIG MUXTOPUS_HOME MUXTOPUS_DIR TMUX
export SHELL=/bin/bash
mkdir -p "$HOME" "$SB/bin"
trap '[ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"' EXIT

BIN="$HOME/.local/bin"
MUXHOME="$HOME/muxhome"
CFG="$HOME/.config/muxtopus/config"
# THE OUTPUT WITHOUT ITS COLOURS. `ok`/`warn` wrap the marker in SGR escapes,
# and a test that greps for "+ tmux" would otherwise be matching the escape
# and not the line.
inst() {
  "$REPO/install.sh" --no-watchdog --no-rc --home "$MUXHOME" --bin "$BIN" "$@" 2>&1 \
    | sed 's/\x1b\[[0-9;]*m//g'
}
# An UNCOMMENTED key: the config template lists every key as a comment at its
# default, so an unanchored grep matches the template and proves nothing.
has_python_key() { grep -q '^MUXTOPUS_PYTHON=' "$CFG"; }

# ---------------------------------------------------------------- 1. the report
echo "== every tool is reported once, with its version"
out="$(inst --dry-run --no-venv)"
# JUST THE FIRST STEP. Step 5 names the interpreter muxtopus will run on,
# which is a different sentence about a different decision; what is under
# test here is that the CHECK does not say the same thing twice.
step1="$(sed -n '/1\/7  Checking what is here/,/2\/7  Folders/p' <<<"$out")"
for tool in tmux git jq; do
  n="$(grep -c "^    . $tool\( \|$\)" <<<"$step1")"
  check "$tool appears on exactly one line (got $n)" test "$n" = 1
done
n="$(grep -c "^    . python3\( \|$\)" <<<"$step1")"
check "python3 appears on exactly one line (got $n)" test "$n" = 1
check "and the line carries its version" grep -qE "^    . (tmux|python3) [0-9]+\.[0-9]" <<<"$step1"
check "the steps are numbered to 7" grep -q "1/7  Checking what is here" <<<"$out"

# ------------------------------------------------- 2. a python3 that is too old
# FIRST ON PATH and lying about its version: 3.9 is the real floor -- the
# Python half is written with `X | None` -- and it is what Debian 11 and
# Ubuntu 20.04 ship.
cat > "$SB/bin/python3" <<EOF
#!/usr/bin/env bash
case " \$* " in
  *" import sys; sys.exit(sys.version_info < (3, 10))"*) exit 1 ;;
  *"sys.version_info[:3]"*) echo "3.9.18"; exit 0 ;;
  *"sys.version_info[:2]"*) echo "3.9"; exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$SB/bin/python3"
export PATH="$SB/bin:$PATH"

echo "== --no-embedded-python: it says what is lost and downloads nothing"
out="$(inst --no-venv --no-embedded-python)"
check "it names the version it found" grep -q "python3 3.9.18 is older than 3.10" <<<"$out"
check "and says nothing will be fetched" grep -q -- "--no-embedded-python" <<<"$out"
check "no python was unpacked" test ! -d "$MUXHOME/python"
if has_python_key; then bad "and no MUXTOPUS_PYTHON was written"
else ok "and no MUXTOPUS_PYTHON was written"; fi

# ------------------------------------------------------- 3. a release to fetch
# The asset list the real one publishes, cut to the two fields this reads.
mkdir -p "$SB/rel/python/bin"
cat > "$SB/rel/python/bin/python3" <<EOF
#!/usr/bin/env bash
exec "$REAL_PY" "\$@"
EOF
chmod +x "$SB/rel/python/bin/python3"
case "$(uname -m)" in
  x86_64|amd64)  ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) echo "no asset name for $(uname -m); skipping the fetch"; ARCH="" ;;
esac
ASSET="cpython-3.13.7+20260901-$ARCH-unknown-linux-gnu-install_only.tar.gz"
OLDER="cpython-3.11.9+20260901-$ARCH-unknown-linux-gnu-install_only.tar.gz"
( cd "$SB/rel" && tar -czf "$ASSET" python && cp "$ASSET" "$OLDER" )
for a in "$ASSET" "$OLDER"; do
  sha256sum "$SB/rel/$a" | cut -d' ' -f1 > "$SB/rel/$a.sha256"
done
# Both versions in the list, and the OLDER one first, so "it takes the newest"
# is a claim this proves rather than one the order of the file made true.
{
  printf '{"assets":[\n'
  printf '  {"browser_download_url": "file://%s/rel/%s"},\n' "$SB" "$OLDER"
  printf '  {"browser_download_url": "file://%s/rel/%s"}\n' "$SB" "$ASSET"
  printf ']}\n'
} > "$SB/rel/latest.json"
export MUXTOPUS_PBS_API="file://$SB/rel/latest.json"

if [ -n "$ARCH" ]; then
  echo "== the sha256 gate: a tarball that does not match is refused"
  printf 'deadbeef' > "$SB/rel/$ASSET.sha256"
  out="$(inst --no-venv)"
  check "it says the sum did not match" grep -q "sha256 MISMATCH" <<<"$out"
  check "and unpacks nothing" test ! -d "$MUXHOME/python"
  if has_python_key; then bad "and still writes no MUXTOPUS_PYTHON"
  else ok "and still writes no MUXTOPUS_PYTHON"; fi
  sha256sum "$SB/rel/$ASSET" | cut -d' ' -f1 > "$SB/rel/$ASSET.sha256"

  echo "== the fetch: checked, unpacked, probed, written down"
  out="$(inst --no-venv)"
  check "it took the NEWEST build in the list" grep -q "cpython-3.13.7" <<<"$out"
  check "it checked the sum" grep -q "sha256 matches the published sum" <<<"$out"
  check "the interpreter is there" test -x "$MUXHOME/python/bin/python3"
  check "and it runs" "$MUXHOME/python/bin/python3" -c 'import sys; sys.exit(0)'
  check "the config names it" grep -q "^MUXTOPUS_PYTHON=\"$MUXHOME/python/bin/python3\"" "$CFG"
  check "and it said so out loud" grep -q "MUXTOPUS_PYTHON=$MUXHOME/python/bin/python3" <<<"$out"

  echo "== NOT on PATH, and not the machine's python"
  check "nothing was linked into the bin dir" test ! -e "$BIN/python3"
  check "nor python"                          test ! -e "$BIN/python"
  check "and the installer said so" grep -q "nothing was added to PATH" <<<"$out"

  echo "== profile.sh then runs the python half on it"
  got="$(env -u MUXTOPUS_DIR MUXTOPUS_CONFIG="$CFG" bash -c \
         ". '$REPO/profile.sh'; mux_load_config ''; printf '%s' \"\$MUX_PYTHON\"")"
  check "MUX_PYTHON is the fetched one (got ${got:-empty})" \
        test "$got" = "$MUXHOME/python/bin/python3"

  echo "== a second install leaves it alone"
  out="$(inst --no-venv)"
  check "it is recognised rather than fetched again" grep -q "is already here" <<<"$out"
  check "and the config keeps ONE line for it" \
        test "$(grep -c '^MUXTOPUS_PYTHON=' "$CFG")" = 1
fi

echo
echo "$PASSES passed, $FAILS failed"
[ "$FAILS" = 0 ]
