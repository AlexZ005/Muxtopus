#!/usr/bin/env bash
# e2e-pc-remote.sh -- the far half of a pc e2e slot. lib/e2e-pc.sh copies it
# to the pc host (~/.cache/muxtopus-pc/bin/) and calls it over ssh, one
# subcommand per step; nobody types it.
#
#   probe                         HOME, the GPU path, whether muxtopus is installed here
#   claim d:<path>|f:<path>...    may a mirror be written there? ("ok"/"no <why>" lines; an
#                                 ok folder gets its marker, an ok file its parent folder)
#   prep <dir>...                 node_modules for each dir, by its lockfile's hash
#   serve <dir> <port> [<url>]    that dir's dev server on that port (lane-dev), warmed up
#   status <port>                 is lane-dev running a server on it here (rc)
#   envin <id>                    stdin -> the run's environment file; the run's start stamp
#   run <id> <cwd> <gpu> -- cmd   the command, in its own session, killed if the caller goes
#   back <id> <path>...           NUL-separated files written since the stamp under each path
#   clean <id> [<port>]           the run's files; the dev server on <port> if it started one
#
# EVERYTHING AT THE SAME PATH. This account's HOME is the caller's HOME (e2e-pc.sh
# refuses a host where it is not), so a tree, an evidence folder or a default
# like `process.env.OUT || '/tmp'` means the same file on both machines and
# nothing in a lane's command has to be rewritten. The price is the CLAIM: a
# mirror is only ever written where nothing is, or where a mirror already is
# (a `.muxtopus-mirror` marker at its top). A real checkout on this machine --
# a lane that lives here -- is never synced over; the run goes elsewhere.
set -uo pipefail
BASE="$HOME/.cache/muxtopus-pc"
BIN="$BASE/bin"
MARK=.muxtopus-mirror
mkdir -p "$BASE/runs" "$BASE/nm"
export PATH="$HOME/.local/bin:$PATH"
# The installed lane-dev when muxtopus is installed here (its state is then the
# one `lane-dev status` shows a person on this machine), else the copy shipped
# beside this script.
LANE_DEV="$HOME/.local/bin/lane-dev"; [ -x "$LANE_DEV" ] || LANE_DEV="$BIN/lane-dev"

starttime() {
  local st; read -r st < "/proc/$1/stat" 2>/dev/null || return 1
  st="${st##*) }"; local -a f; read -r -a f <<<"$st"; printf '%s' "${f[19]}"
}

cmd_probe() {
  local gpu=cpu
  # WSL2's GPU: /dev/dxg plus Mesa's d3d12 driver (lib/pw-pc-shim.cjs says why).
  if [ -e /dev/dxg ] && [ -d /usr/lib/wsl/lib ] && ls /usr/lib/*/dri/d3d12_dri.so >/dev/null 2>&1; then gpu=d3d12; fi
  printf 'home=%s\ngpu=%s\nslots=%s\nnode=%s\n' "$HOME" "$gpu" \
    "$([ -x "$HOME/.local/bin/e2e-slot" ] && echo installed || echo none)" "$(node -v 2>/dev/null || echo none)"
}

# Inside a mirror: the path or one of its ancestors (up to HOME) carries the marker.
in_mirror() {
  local p="$1"
  while [ -n "$p" ] && [ "$p" != / ] && [ "$p" != "$HOME" ]; do
    [ -e "$p/$MARK" ] && return 0
    p="${p%/*}"
  done
  return 1
}
# A checkout: the path or an ancestor (up to HOME) has .git.
in_checkout() {
  local p="$1"
  while [ -n "$p" ] && [ "$p" != / ] && [ "$p" != "$HOME" ]; do
    [ -e "$p/.git" ] && return 0
    p="${p%/*}"
  done
  return 1
}

cmd_claim() {
  local a p kind why
  for a in "$@"; do
    kind="${a%%:*}"; p="${a#?:}"; why=""
    case "$p" in "$HOME"/?*|/tmp/?*) ;; *) why="outside HOME and /tmp" ;; esac
    if [ -z "$why" ] && ! in_mirror "$p"; then
      if [ -d "$p" ] && [ -n "$(ls -A "$p" 2>/dev/null)" ]; then why="is a folder of this machine's own (no $MARK)"
      elif in_checkout "$p"; then why="is inside a checkout of this machine's own"
      fi
    fi
    if [ -n "$why" ]; then echo "no $p $why"; continue; fi
    if [ "$kind" = d ]; then mkdir -p "$p" && { [ -e "$p/$MARK" ] || in_mirror "$p" || : > "$p/$MARK"; }
    else mkdir -p "${p%/*}"; fi
    echo "ok $p"
  done
}

# node_modules from a cache keyed by the lockfile and node's version: `npm ci`
# once per hash, every later tree with the same lockfile gets a hard-linked
# copy (cp -al: a second or so, no extra disk). Hard links share the files, so
# a package patched IN PLACE would change the cache too; nothing a test run
# does writes there (vite's .vite/ is new files), and the stamp is checked on
# every run. Never --legacy-peer-deps: what `npm ci` refuses is a lane's bug to
# see, not ours to paper over.
cmd_prep() {
  local d h lock c
  for d in "$@"; do
    [ -f "$d/package-lock.json" ] || continue
    h="$( { cat "$d/package-lock.json"; node -v; } | sha256sum | cut -c1-24)"
    [ "$(cat "$d/node_modules/.muxtopus-pc-lock" 2>/dev/null)" = "$h" ] && { touch "$BASE/nm/$h" 2>/dev/null; continue; }
    c="$BASE/nm/$h"
    exec {lock}>"$BASE/nm/$h.lock"; flock "$lock"
    if [ -f "$c/.complete" ]; then
      rm -rf -- "${d:?}/node_modules"; cp -al "$c/node_modules" "$d/node_modules" || { exec {lock}>&-; return 1; }
      echo "e2e-pc: node_modules for $d from the cache ($h)" >&2
    else
      echo "e2e-pc: npm ci in $d (new lockfile $h)" >&2
      rm -rf -- "${d:?}/node_modules"
      ( cd "$d" && npm ci --no-audit --no-fund ) >&2 || { echo "e2e-pc: npm ci failed in $d" >&2; exec {lock}>&-; return 1; }
      rm -rf -- "${c:?}"; mkdir -p "$c"
      cp -al "$d/node_modules" "$c/node_modules" && : > "$c/.complete"
    fi
    printf '%s\n' "$h" > "$d/node_modules/.muxtopus-pc-lock"
    touch "$c"; exec {lock}>&-
  done
  # A cache nothing has used for two weeks goes. Measured: one lockfile's tree
  # is 437 MB, so a month of lockfile bumps would otherwise be gigabytes.
  find "$BASE/nm" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} + 2>/dev/null
  return 0
}

# The dev server, through lane-dev: its idle watcher stops it once nothing has
# used it for LANE_DEV_IDLE minutes, so a server started for one run is still
# warm for the next one a minute later and gone an hour after. Then one request
# to the app's URL: vite optimises dependencies on the FIRST page load (measured
# here: 20 s for the first answer, 6 s per run after), and a test's 30 s
# navigation timeout should not be what pays for it.
cmd_serve() {
  local dir="$1" port="$2" url="${3:-}" rc
  "$LANE_DEV" start "$dir" "$port" >&2; rc=$?
  [ "$rc" = 0 ] || return "$rc"
  [ -n "$url" ] && command -v curl >/dev/null && curl -sk -o /dev/null -m 120 "$url" 2>/dev/null
  return 0
}

cmd_envin() {
  local d="$BASE/runs/$1"
  mkdir -p "$d"; ( umask 077; cat > "$d/env" ); : > "$d/stamp"
}

cmd_run() {
  local id="$1" cwd="$2" gpu="$3" d="$BASE/runs/$1" pid st rc
  shift 3; [ "${1:-}" = -- ] && shift
  [ -f "$d/env" ] || { echo "e2e-pc: no environment for run $id" >&2; return 2; }
  set -a; . "$d/env"; set +a
  export PATH="$HOME/.local/bin:$PATH" LANG=C.UTF-8
  if [ "$gpu" = d3d12 ]; then
    export GALLIUM_DRIVER=d3d12 PW_PC_GPU=d3d12 LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--require $BIN/pw-pc-shim.cjs"
  fi
  cd "$cwd" || { echo "e2e-pc: $cwd is not on this machine" >&2; return 2; }
  # THIS MACHINE'S OWN SLOTS when muxtopus is installed here: lanes that live
  # here run their e2e through the same lock files, so the two kinds of run
  # share this machine's capacity instead of each assuming all of it.
  [ -x "$HOME/.local/bin/e2e-slot" ] && set -- "$HOME/.local/bin/e2e-slot" --local --wait "${E2E_PC_WAIT:-5400}" -- "$@"
  # Its own session, so one signal reaches every process it starts; stdin is
  # not the caller's (an e2e command reads none), because OUR stdin is the
  # caller's lifeline: e2e-pc.sh holds the other end open for exactly as long
  # as it lives, and EOF on it -- the caller killed, the WiFi gone, the Deck
  # asleep -- stops the run here instead of leaving it to run on unseen.
  # fd 3 is the lifeline: a background job of a non-interactive shell gets
  # /dev/null for stdin, so the watcher must not read fd 0 (measured: it did,
  # saw EOF at once and killed every run 0.0 s in).
  exec 3<&0
  setsid "$@" < /dev/null 3<&- &
  pid=$!; st="$(starttime "$pid")"
  printf '%s %s\n' "$pid" "$st" > "$d/pid"
  (
    exec > /dev/null 2>&1
    cat <&3 > /dev/null
    [ -e "$d/done" ] && exit 0
    # Only the group we started: a pid alone could be another program by now.
    [ "$(starttime "$pid")" = "$st" ] || exit 0
    kill -TERM -- "-$pid"; sleep 5
    [ "$(starttime "$pid")" = "$st" ] && kill -KILL -- "-$pid"
  ) &
  exec 3<&-
  wait "$pid"; rc=$?
  : > "$d/done"
  return "$rc"
}

# What the run wrote: files newer than its stamp under each path, plus /tmp's
# own new files (two levels: tests default to `OUT || '/tmp'`). Not
# node_modules, .git or the build caches -- those are this machine's, and the
# caller's are its own.
cmd_back() {
  local id="$1" st="$BASE/runs/$1/stamp" p
  shift
  [ -f "$st" ] || return 0
  {
    for p in "$@"; do
      [ -e "$p" ] || continue
      find "$p" \( -name node_modules -o -name .git -o -name .svelte-kit -o -name .vite -o -name "$MARK" \) -prune \
        -o -type f -newer "$st" -print0 2>/dev/null
    done
    find /tmp -mindepth 1 -maxdepth 2 \( -name 'playwright*' -o -name 'pw-*' -o -name 'node-compile-cache' -o -name 'v8-compile-cache*' -o -name 'muxtopus-*' -o -name '.*' \) -prune \
      -o -type f -user "$(id -u)" -newer "$st" -print0 2>/dev/null
  } | sort -zu
}

cmd_clean() {
  local id="$1" port="${2:-}"
  [ -n "$port" ] && "$LANE_DEV" stop "$port" >&2
  case "$id" in ''|*/*|.*) return 0 ;; esac
  rm -rf -- "${BASE:?}/runs/$id"
  # Runs the caller never cleaned (killed, asleep): a day is plenty.
  find "$BASE/runs" -mindepth 1 -maxdepth 1 -type d -mtime +1 -exec rm -rf {} + 2>/dev/null
  return 0
}

case "${1:-}" in
  probe) shift; cmd_probe "$@" ;;
  claim) shift; cmd_claim "$@" ;;
  prep) shift; cmd_prep "$@" ;;
  serve) shift; cmd_serve "$@" ;;
  status) "$LANE_DEV" status "${2:-}" --quiet ;;
  envin) shift; cmd_envin "$@" ;;
  run) shift; cmd_run "$@" ;;
  back) shift; cmd_back "$@" ;;
  clean) shift; cmd_clean "$@" ;;
  *) echo "e2e-pc-remote.sh: probe | claim | prep | serve | status | envin | run | back | clean" >&2; exit 2 ;;
esac
