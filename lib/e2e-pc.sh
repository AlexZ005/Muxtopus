#!/usr/bin/env bash
# e2e-pc.sh -- e2e-slot's pc slots: the whole run on another machine.
#
#   e2e-pc.sh probe [--quick] <host>                is it up, and usable (rc 0); --quick: up
#   e2e-pc.sh run <host> [--dev DIR PORT] -- cmd    the run; the command's exit code
#
# e2e-slot calls it; nobody needs to. <host> is a name from hosts.conf
# (lib/hosts.sh). Exit 76 from `run` means "not on this host, nothing was
# started": e2e-slot then gives the run another slot.
#
# WHY A WHOLE RUN AND NOT JUST THE BROWSER. A remote slot (MUXTOPUS_E2E_REMOTE)
# moves only Chromium; every page.evaluate and locator call still crosses the
# network to it. Measured on the Deck's WiFi (8.6 ms average ping): suites of
# many small round trips got SLOWER remotely (lock-settings 247 s against 210 s
# local, llms-txt 13 against 10), and the dev server and the test's node still
# sat in the Deck's RAM. A pc slot puts the tree, its node_modules, the dev
# server, the test and the browser on the far machine together and only sends
# the output back.
#
# THE STEPS, each a call over one ssh control connection:
#   1. the far half (lib/e2e-pc-remote.sh, lane-dev, the GPU shim) is copied over
#   2. the TREE -- the git top level of the run's folder, else the nearest folder
#      with a package.json -- is mirrored with rsync (--delete; never node_modules
#      or .git), and so is every input the command names: an absolute path under
#      HOME or /tmp in an argument or an environment value that exists here
#      (a MODULES_REPO, a scene zip, an evidence folder)
#   3. node_modules there, by lockfile hash: `npm ci` once per hash (remote half)
#   4. the dev server, when the run needs one: --dev's, or the port in APP_URL
#      when its host is this machine (localhost, or a name /etc/hosts points at
#      a loopback address) -- the same port number there, started with lane-dev
#      as this machine's lane-dev started it, left to lane-dev's idle timer
#      unless --dev asked for it (then it stops after the run, as here)
#   5. the command, as given, in the same folder, with the environment below,
#      its output streamed back as it runs
#   6. every file it wrote -- in the tree, in those paths, in /tmp -- copied back
#      to the same path here (rsync --update: a file changed here meanwhile wins)
#   7. the run's files there removed
#
# THE SAME PATHS. The far account's HOME must be this one's (probe refuses a
# host where it is not): then no path in a lane's command, its environment or
# its tests' defaults needs rewriting. The far half refuses to write a mirror
# over a folder of that machine's own -- see its header.
#
# THE ENVIRONMENT. Everything exported here goes, except what describes THIS
# machine or session, or is a credential:
#   PATH HOME USER LOGNAME SHELL PWD OLDPWD SHLVL TERM* COLORTERM TMPDIR LANG
#   LANGUAGE LC_* TMUX* SSH_* DISPLAY WAYLAND_* XAUTHORITY XDG_* DBUS_*
#   LD_* NODE_OPTIONS PLAYWRIGHT_BROWSERS_PATH PW_REMOTE_* npm_* NVM_*
#   CLAUDE* ANTHROPIC_* MUXTOPUS_* WATCHDOG_* MAIL HOSTNAME EDITOR VISUAL PAGER
#   LS_COLORS LESS* PS1-4 PROMPT_COMMAND HIST* DESKTOP_SESSION SESSION_MANAGER
#   GTK_* QT_* KDE_* GNOME_* SDL_* STEAM* PULSE_* PIPEWIRE_* XCURSOR_* MOZ_*
#   KONSOLE_* VTE_* WINDOWID INVOCATION_ID JOURNAL_STREAM SYSTEMD_* MANAGERPID
#   MEMORY_PRESSURE_* DEBUGINFOD_* GPG_* SUDO_* OTEL_* GH_* GITHUB_* AWS_*
#   and any name containing TOKEN, SECRET, PASSWORD, PASSWD, API_KEY,
#   PRIVATE_KEY or CREDENTIAL.
# E2E_PC_INPUTS="path path" names more inputs: what a script sources by itself.
# E2E_PC_ENV="NAME NAME" sends those names anyway. LANG is C.UTF-8 there
# (a locale this machine has may not exist on that one). NODE_OPTIONS is
# dropped because e2e-slot's own (the remote-browser shim) names a file here.
#
# The command's stdin is not forwarded: ssh's stdin is the run's lifeline (the
# far half stops the run when it closes), held open by this script alone.
set -uo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
ROOT="$(dirname "$HERE")"
# shellcheck source=lib/hosts.sh
. "$HERE/hosts.sh"
RBASE='$HOME/.cache/muxtopus-pc'
RBIN="$RBASE/bin"

# NONE OF THE CALLER'S DESCRIPTORS. e2e-slot holds its slot as a flock on a
# descriptor it opened; the ssh control master this starts lives for minutes
# after the run, and one that inherited that descriptor would hold the slot
# for as long. e2e-slot's own copy keeps the lock -- closing ours does not
# release it.
for _fd in /proc/$$/fd/*; do
  _fd="${_fd##*/}"
  case "$_fd" in 0|1|2|255|*[!0-9]*) ;; *) eval "exec $_fd>&-" 2>/dev/null ;; esac
done

say() { echo "e2e-slot: $*" >&2; }
now_ms() { local t; t="$(date +%s%N)"; printf '%s' "$(( t / 1000000 ))"; }
secs() { local ms=$(( $(now_ms) - $1 )); printf '%d.%d' "$(( ms / 1000 ))" "$(( ms % 1000 / 100 ))"; }

# One remote call: the far half's subcommand with its arguments quoted for the
# far shell. Extra ssh options never needed: the control socket carries it.
rq() { local q; q="$(printf '%q ' "$@")"; "${MUX_HOST_SSH[@]}" "bash $RBIN/e2e-pc-remote.sh $q"; }

host_up() {
  local host="$1" out
  mux_host_ssh "$host" || { say "pc host '$host' is not in $MUX_HOSTS_FILE"; return 1; }
  mux_host_master "$host" || return 1
  # The far half may not be there yet (a first run): ship it here, it is cheap.
  ship || return 1
  out="$(rq probe 2>/dev/null)" || return 1
  PC_HOME="$(sed -n 's/^home=//p' <<<"$out")"
  PC_GPU="$(sed -n 's/^gpu=//p' <<<"$out")"
  PC_NODE="$(sed -n 's/^node=//p' <<<"$out")"
  if [ "$PC_HOME" != "$HOME" ]; then
    say "pc host '$host' has HOME=$PC_HOME, this machine $HOME: a pc slot needs the same HOME there (docs/pc-host.md)"
    return 2
  fi
  if [ "$PC_NODE" = none ]; then say "pc host '$host' has no node on PATH"; return 2; fi
  return 0
}

# The far half, lane-dev and the GPU shim, into ~/.cache/muxtopus-pc/bin there.
ship() {
  rsync -a -e "$(rsh)" "$HERE/e2e-pc-remote.sh" "$HERE/pw-pc-shim.cjs" "$ROOT/lane-dev" \
    "${MUX_HOST_SSH[-1]}:.cache/muxtopus-pc/bin/" 2>/dev/null && return 0
  # rsync wants the folder to exist.
  "${MUX_HOST_SSH[@]}" 'mkdir -p .cache/muxtopus-pc/bin' && \
    rsync -a -e "$(rsh)" "$HERE/e2e-pc-remote.sh" "$HERE/pw-pc-shim.cjs" "$ROOT/lane-dev" \
      "${MUX_HOST_SSH[-1]}:.cache/muxtopus-pc/bin/"
}
# rsync's -e: the ssh argv without its target, as one string (printf %q, so a
# key path with a space survives rsync's own word splitting).
rsh() { printf '%q ' "${MUX_HOST_SSH[@]:0:${#MUX_HOST_SSH[@]}-1}"; }

# The tree a run belongs to.
tree_of() {
  local d="$1" t
  t="$(git -C "$d" rev-parse --show-toplevel 2>/dev/null)" && { printf '%s' "$t"; return 0; }
  t="$d"
  while [ -n "$t" ] && [ "$t" != "$HOME" ] && [ "$t" != / ]; do
    [ -f "$t/package.json" ] && { printf '%s' "$t"; return 0; }
    t="${t%/*}"
  done
  printf '%s' "$d"
}

# Names /etc/hosts points at a loopback address: an APP_URL on one of them is
# a server on THIS machine, so it has to be started over there too.
is_local_host() {
  local h="$1"
  case "$h" in localhost|127.*|::1|'[::1]') return 0 ;; esac
  awk -v h="$h" '{ sub(/#.*/, "") } $1 ~ /^(127\.|::1$)/ { for (i = 2; i <= NF; i++) if (tolower($i) == tolower(h)) f = 1 }
    END { exit !f }' /etc/hosts 2>/dev/null
}

DENY_RE='^(PATH|HOME|USER|LOGNAME|SHELL|PWD|OLDPWD|SHLVL|_|TERM.*|COLORTERM|TMPDIR|LANG|LANGUAGE|LC_.*|TMUX.*|SSH_.*|DISPLAY|WAYLAND_.*|XAUTHORITY|XDG_.*|DBUS_.*|LD_.*|NODE_OPTIONS|PLAYWRIGHT_BROWSERS_PATH|PW_REMOTE_.*|npm_.*|NVM_.*|CLAUDE.*|ANTHROPIC_.*|MUXTOPUS_.*|WATCHDOG_.*|MAIL|HOSTNAME|EDITOR|VISUAL|PAGER|LS_COLORS|LESS.*|PS[1-4]|PROMPT_COMMAND|HIST.*|DESKTOP_SESSION|SESSION_MANAGER|GTK_.*|QT_.*|KDE_.*|GNOME_.*|SDL_.*|STEAM.*|PULSE_.*|PIPEWIRE_.*|XCURSOR_.*|MOZ_.*|KONSOLE_.*|VTE_.*|WINDOWID|INVOCATION_ID|JOURNAL_STREAM|SYSTEMD_.*|MANAGERPID|MEMORY_PRESSURE_.*|DEBUGINFOD_.*|GPG_.*|SUDO_.*|OTEL_.*|GH_.*|GITHUB_.*|AWS_.*|E2E_SLOT_REMOTE|E2E_PC_ENV|E2E_PC_INPUTS|E2E_SLOTS|E2E_SLOT_LOCK|E2E_PREFER|E2E_REMOTE|E2E_REMOTE_GPU|E2E_PC)$'
SECRET_RE='(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL)'
# Names that point at a toolchain on this machine: sent (harmless if absent
# there), never taken as a path to mirror.
TOOL_RE='(_HOME|_ROOT|_PREFIX|_PATH)$|^(VIRTUAL_ENV|CONDA_.*|PYTHON.*|JAVA_.*|ANDROID_.*|GOPATH|GOROOT|CARGO_.*|RUSTUP_.*|GRADLE_.*|PNPM_.*|BUN_.*|DENO_.*)$'

# Sent names, one `export NAME=value` line each, printf %q quoted.
env_file() {
  local n force=" ${E2E_PC_ENV:-} "
  for n in $(compgen -e); do
    [[ "$n" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ "$force" != *" $n "* ]]; then
      [[ "$n" =~ $DENY_RE ]] && continue
      [[ "${n^^}" =~ $SECRET_RE ]] && continue
    fi
    printf 'export %s=%q\n' "$n" "${!n}"
  done
}

# probe --quick: only "does ssh answer" -- what e2e-slot asks while it holds a
# slot's lock. The full check (the far half shipped, the same HOME, node) is
# the run's first step anyway, and a refusal there is exit 76, which e2e-slot
# already handles; doing it twice cost 1.7 s a run (measured).
cmd_probe() {
  if [ "${1:-}" = --quick ]; then
    mux_host_ssh "$2" || { say "pc host '$2' is not in $MUX_HOSTS_FILE"; return 1; }
    mux_host_master "$2" && "${MUX_HOST_SSH[@]}" true </dev/null
    return
  fi
  host_up "$1"
}

cmd_run() {
  local host="$1"; shift
  local dev_dir="" dev_port=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --dev) dev_dir="$2"; dev_port="$3"; shift 3 ;;
      --) shift; break ;;
      *) break ;;
    esac
  done
  local t0; t0="$(now_ms)"
  host_up "$host" || return 76
  local base="${dev_dir:-$PWD}" tree cwd="$PWD"
  base="$(readlink -f "$base")"; tree="$(tree_of "$base")"
  case "$tree" in "$HOME"/?*/?*) ;; *) say "pc: $tree is not a tree under $HOME; not on $host"; return 76 ;; esac
  case "$cwd/" in "$tree"/*) ;; *) say "pc: the run's folder $cwd is outside its tree $tree; not on $host"; return 76 ;; esac

  # THE SERVER: which port, which folder, which command.
  local url="" port="" sdir="" scmd="" a
  for a in "$@"; do case "$a" in APP_URL=*) url="${a#APP_URL=}" ;; esac; done
  [ -z "$url" ] && url="${APP_URL:-}"
  if [ -n "$dev_port" ]; then port="$dev_port"; sdir="$(readlink -f "$dev_dir")"
  elif [[ "$url" =~ ^https?://(\[[^]]+\]|[^/:]+):([0-9]+) ]] && is_local_host "${BASH_REMATCH[1]}"; then
    port="${BASH_REMATCH[2]}"
    # The folder and command this machine's lane-dev runs on that port, if it
    # does; else the tree's own `npm run dev`.
    local st="${XDG_STATE_HOME:-$HOME/.local/state}/lane-dev/$port"
    if [ -f "$st/dir" ]; then sdir="$(cat "$st/dir")"; scmd="$(cat "$st/cmd" 2>/dev/null)"; fi
    if [ -z "$sdir" ]; then
      if grep -q '"dev"[[:space:]]*:' "$tree/package.json" 2>/dev/null; then sdir="$tree"
      else say "pc: nothing to serve $url from (no lane-dev server here on $port, no dev script in $tree); not on $host"; return 76; fi
    fi
  fi
  [ -n "$sdir" ] && case "$sdir" in "$HOME"/?*/?*) ;; *) say "pc: the server's folder $sdir is not under $HOME; not on $host"; return 76 ;; esac
  [ "$scmd" = "npm run dev -- --port $port --strictPort" ] && scmd=""

  # THE PATHS: the tree (and the server's folder), and what the command names.
  local -a trees=("$tree") inputs=() backs=("$tree") tok v n
  [ -n "$sdir" ] && [ "$sdir" != "$tree" ] && case "$sdir/" in "$tree"/*) ;; *) trees+=("$sdir"); backs+=("$sdir") ;; esac
  # Arguments count whole; environment values only when neither the name nor
  # the place says "this machine's own": JAVA_HOME, a venv, ~/.local/state
  # are on every shell's environment, and the first version of this mirrored
  # a JDK to the far side on every run (measured: 2-4 s a run, for nothing).
  local -a toks=("$@")
  # E2E_PC_INPUTS: paths no argument or variable names -- what a script the
  # command runs sources by itself (a battery's env.sh and the repos IT
  # names). Mirrored and copied back like any other input.
  local x
  for x in ${E2E_PC_INPUTS:-}; do toks+=("$x"); done
  for n in $(compgen -e); do
    [[ "$n" =~ $DENY_RE ]] && continue
    [[ "$n" =~ $TOOL_RE ]] && continue
    v="${!n}"
    case "$v" in "$HOME"/.local/*|"$HOME"/.cache/*|"$HOME"/.config/*|"$HOME"/.npm/*|"$HOME"/.nvm/*|"$HOME"/.cargo/*|"$HOME"/.rustup/*|"$HOME"/.gradle/*|"$HOME"/.m2/*|"$HOME"/.android/*|"$HOME"/.ssh/*|"$HOME"/.gnupg/*|"$HOME"/.claude*|"$HOME"/.var/*|"$HOME"/.steam*|*/.venv/*|*/venv/bin/*) continue ;; esac
    toks+=("$v")
  done
  local -A seen=()
  for tok in "${toks[@]}"; do
    for v in "$tok" "${tok#*=}"; do
      v="${v%/}"
      case "$v" in "$HOME"/?*|/tmp/?*) ;; *) continue ;; esac
      [ -n "${seen[$v]:-}" ] && continue
      seen[$v]=1
      [[ "$v" == *$'\n'* ]] && continue
      local inside=0 t
      for t in "${trees[@]}"; do case "$v/" in "$t"/*) inside=1 ;; esac; case "$t/" in "$v"/*) inside=2 ;; esac; done
      [ "$inside" = 1 ] && continue
      [ "$inside" = 2 ] && continue         # an ancestor of the tree: far too big to mirror, and not an output
      backs+=("$v")
      [ -e "$v" ] || continue
      if [ -d "$v" ]; then
        # A folder of HOME's first two levels (~/.code) is never mirrored: it
        # holds everything. Copied back, yes -- a test may write there.
        case "$v" in "$HOME"/*/*/?*|/tmp/?*) inputs+=("d:$v") ;; esac
      else inputs+=("f:$v"); fi
    done
  done

  # 2. MIRROR. The claim first: a folder of the far machine's own is never synced over.
  local t1 out ok_inputs=() line
  t1="$(now_ms)"
  local -a claims=()
  for t in "${trees[@]}"; do claims+=("d:$t"); done
  out="$(rq claim "${claims[@]}" "${inputs[@]}")" || { say "pc: $host did not answer the claim; not on $host"; return 76; }
  while IFS= read -r line; do
    case "$line" in
      "no "*) for t in "${trees[@]}"; do
                [ "${line#no }" != "${line#no "$t" }" ] && { say "pc: $host: ${line#no }; not on $host"; return 76; }
              done
              say "pc: not mirroring ${line#no } -- the run sees $host's own copy" ;;
      "ok "*) ok_inputs+=("${line#ok }") ;;
    esac
  done <<<"$out"
  local -a rs=(rsync -a --delete -e "$(rsh)" --filter='P .muxtopus-mirror' --exclude=node_modules/ --exclude=.git --exclude=.vite/)
  local tgt="${MUX_HOST_SSH[-1]}"
  for t in "${trees[@]}"; do
    "${rs[@]}" "$t/" "$tgt:$t/" || { say "pc: mirroring $t to $host failed; not on $host"; return 76; }
  done
  local i
  for i in "${inputs[@]}"; do
    v="${i#?:}"
    [[ " ${ok_inputs[*]} " == *" $v "* ]] || continue
    for t in "${trees[@]}"; do [ "$v" = "$t" ] && continue 2; done
    if [ "${i%%:*}" = d ]; then
      # Inputs: changed files only, nothing deleted there -- an evidence
      # folder may hold what earlier pc runs wrote and this machine has too.
      rsync -a -e "$(rsh)" --exclude=node_modules/ --exclude=.git "$v/" "$tgt:$v/" || say "pc: could not mirror $v"
    else
      rsync -a -e "$(rsh)" "$v" "$tgt:$v" || say "pc: could not mirror $v"
    fi
  done
  local sync_s; sync_s="$(secs "$t1")"

  # 3. node_modules where this machine has them.
  local t2 deps_s; t2="$(now_ms)"
  local -a nm=()
  while IFS= read -r -d '' line; do
    line="${line%/package-lock.json}"; [ -d "$line/node_modules" ] && nm+=("$line")
  done < <(for t in "${trees[@]}"; do find "$t" -maxdepth 3 -name node_modules -prune -o -name package-lock.json -print0; done
           # An input folder that is a package of its own (a modules repo a
           # test runs `node` in) gets its node_modules the same way.
           for x in "${ok_inputs[@]}"; do [ -f "$x/package-lock.json" ] && printf '%s\0' "$x/package-lock.json"; done)
  if [ ${#nm[@]} -gt 0 ]; then rq prep "${nm[@]}" || { say "pc: dependencies on $host failed; not on $host"; return 76; }; fi
  deps_s="$(secs "$t2")"

  # 4. THE SERVER.
  local t3 srv_s="-" stop_port="" rc
  if [ -n "$port" ]; then
    t3="$(now_ms)"
    # Was it already up there? Then it is not ours to stop, whatever --dev says.
    local was_up=0
    rq status "$port" && was_up=1
    if [ -n "$scmd" ]; then
      "${MUX_HOST_SSH[@]}" "LANE_DEV_CMD=$(printf %q "$scmd") bash $RBIN/e2e-pc-remote.sh serve $(printf '%q ' "$sdir" "$port" "$url")"; rc=$?
    else
      rq serve "$sdir" "$port" "$url"; rc=$?
    fi
    if [ "$rc" != 0 ]; then say "pc: the dev server on $host:$port did not start (lane-dev $rc); not on $host"; return 76; fi
    [ -n "$dev_port" ] && [ "$was_up" = 0 ] && stop_port="$port"
    srv_s="$(secs "$t3")"
  fi

  # 5. THE RUN. Its id is unique on this machine and says whose it is.
  local id gpu sshpid tmp t4
  id="$(date +%Y%m%d-%H%M%S)-$$-${E2E_SLOT:-x}"
  gpu="$(mux_host_get "$host" gpu auto)"
  case "$gpu" in auto) gpu="$PC_GPU" ;; d3d12|cpu) ;; *) gpu=cpu ;; esac
  { env_file; printf 'export E2E_SLOT=%q E2E_SLOT_PC=%q E2E_SLOT_REMOTE=\n' "${E2E_SLOT:-}" "$host"; } | rq envin "$id" \
    || { say "pc: could not hand $host the environment; not on $host"; return 76; }
  say "slot ${E2E_SLOT:-?} is pc: the whole run is on $host (tree $tree; ${port:+server :$port; }GPU $gpu)"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/muxtopus-pc.XXXXXX")" || return 76
  mkfifo "$tmp/hold"
  t4="$(now_ms)"
  "${MUX_HOST_SSH[@]}" "bash $RBIN/e2e-pc-remote.sh run $(printf '%q ' "$id" "$cwd" "$gpu") -- $(printf '%q ' "$@")" < "$tmp/hold" &
  sshpid=$!
  exec {HOLD}>"$tmp/hold"
  # A signal here: let the far side see the lifeline go, then clean up there.
  trap 'exec {HOLD}>&-; kill "$sshpid" 2>/dev/null; wait "$sshpid" 2>/dev/null; rq clean "$id" $stop_port >/dev/null 2>&1; rm -rf -- "${tmp:?}"; exit 130' INT TERM HUP
  wait "$sshpid"; rc=$?
  exec {HOLD}>&-
  trap - INT TERM HUP
  local run_s; run_s="$(secs "$t4")"

  # 6. BACK: what it wrote, to the same paths here.
  local t5 back_s nfiles=0
  t5="$(now_ms)"
  rq back "$id" "${backs[@]}" > "$tmp/back" 2>/dev/null
  # Only under HOME and /tmp, whatever the far side listed; relative to / for --files-from.
  tr '\0' '\n' < "$tmp/back" | grep -E "^($HOME/|/tmp/)" | sed 's|^/||' > "$tmp/list"
  nfiles="$(wc -l < "$tmp/list")"
  if [ "$nfiles" -gt 0 ]; then
    rsync -a --update --omit-dir-times -e "$(rsh)" --files-from="$tmp/list" "$tgt:/" / || say "pc: copying back from $host failed (rc $?): $nfiles files"
  fi
  back_s="$(secs "$t5")"

  # 7. CLEAN.
  rq clean "$id" $stop_port >/dev/null 2>&1
  rm -rf -- "${tmp:?}"
  say "pc run on $host: rc $rc; mirror ${sync_s}s, deps ${deps_s}s, server ${srv_s}s, run ${run_s}s, back ${back_s}s ($nfiles files), all $(secs "$t0")s"
  # 76 is ours: a command that itself exited 76 must not look like "not here".
  [ "$rc" = 76 ] && rc=1
  return "$rc"
}

case "${1:-}" in
  probe) shift; cmd_probe "$@" ;;
  run) shift; cmd_run "$@" ;;
  *) echo "usage: e2e-pc.sh probe <host> | run <host> [--dev DIR PORT] -- cmd" >&2; exit 2 ;;
esac
