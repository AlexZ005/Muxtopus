# hosts.sh -- the other machines muxtopus may use, read from a file that is
# never in the repository. Sourced, not run.
#
#   . lib/hosts.sh
#   mux_host_names                 every host the file defines, one per line
#   mux_host_get pc ssh            one key of one host ("" when unset)
#   mux_host_get pc e2e_slots 1    ... with a default
#   mux_host_ssh pc                fills the array MUX_HOST_SSH with the ssh argv
#
# THE FILE is ~/.config/muxtopus/hosts.conf (beside `config`; MUXTOPUS_HOSTS
# moves it). One section per host; the section name is the NAME every other
# setting uses -- `MUXTOPUS_E2E_PC=pc`, a schedule entry's `host: pc` -- so an
# address is written down once, on the machine that uses it:
#
#   [pc]
#   ssh = lanes@192.0.2.10      # anything ssh takes: user@host, or a ~/.ssh/config alias
#   port = 22022                # optional
#   key = ~/.ssh/muxtopus-pc    # optional; IdentitiesOnly when given
#   e2e_slots = 2               # pc e2e slots this machine sends there (default 1)
#   gpu = auto                  # pc slots: auto (d3d12 when the host has /dev/dxg), d3d12, cpu
#   lanes = 4                   # lanes it may run (the lane host; see docs/pc-host.md)
#
# WHY A FILE OF ITS OWN AND NOT config KEYS. muxtopus is published, and its
# config keys have defaults written in the repository; an address, a user
# name or a key path is exactly what must never land there by accident (a
# commit of a locally edited default would publish it). A separate file with
# no defaults has nothing to commit, and `tests/test_no_private.py` fails on an
# address of this network in any tracked file.
#
# Comments are `#` to the end of the line; whitespace around `=` is ignored.
# A key may only hold one line. Nothing here executes the file.

MUX_HOSTS_FILE="${MUXTOPUS_HOSTS:-$(dirname "${MUXTOPUS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/muxtopus/config}")/hosts.conf}"

mux_host_names() {
  [ -r "$MUX_HOSTS_FILE" ] || return 0
  awk '{ sub(/#.*/, ""); gsub(/^[ \t]+|[ \t]+$/, "") }
       /^\[[A-Za-z0-9_.-]+\]$/ { print substr($0, 2, length($0) - 2) }' "$MUX_HOSTS_FILE"
}

mux_host_get() {
  local host="$1" key="$2" def="${3:-}" v=""
  if [ -r "$MUX_HOSTS_FILE" ]; then
    v="$(awk -v h="$host" -v k="$key" '
      { sub(/#.*/, ""); gsub(/^[ \t]+|[ \t]+$/, "") }
      /^\[.*\]$/ { cur = substr($0, 2, length($0) - 2); next }
      cur == h && index($0, "=") {
        name = substr($0, 1, index($0, "=") - 1); val = substr($0, index($0, "=") + 1)
        gsub(/^[ \t]+|[ \t]+$/, "", name); gsub(/^[ \t]+|[ \t]+$/, "", val)
        if (name == k) { out = val; found = 1 }
      }
      END { if (found) print out }' "$MUX_HOSTS_FILE")"
  fi
  printf '%s' "${v:-$def}"
}

# The ssh command line for a host, in MUX_HOST_SSH (an array, so a key path
# with a space survives). BatchMode: a host that wants a password is down, not
# a prompt in somebody's pane. The control socket makes the half-dozen calls a
# pc run makes one TCP+key exchange (measured over the Deck's WiFi to a WSL
# distro: 250-380 ms a call without it, 50-180 ms with it); mux_host_master starts it
# with no descriptors of ours, because a master that inherited a pipe would
# hold a caller's `| tee` open for ControlPersist seconds.
mux_host_ssh() {
  local host="$1" target port key
  target="$(mux_host_get "$host" ssh)"
  [ -n "$target" ] || return 1
  port="$(mux_host_get "$host" port)"
  key="$(mux_host_get "$host" key)"
  key="${key/#\~/$HOME}"
  MUX_HOST_SSH=(ssh -o BatchMode=yes -o ConnectTimeout="${MUX_HOST_TIMEOUT:-5}" -o ServerAliveInterval=15
                -o ServerAliveCountMax=4 -o ControlMaster=no
                -o ControlPath="${XDG_RUNTIME_DIR:-/tmp}/muxtopus-ssh-%C")
  [ -n "$port" ] && MUX_HOST_SSH+=(-p "$port")
  [ -n "$key" ] && MUX_HOST_SSH+=(-i "$key" -o IdentitiesOnly=yes)
  MUX_HOST_SSH+=("$target")
  return 0
}

# A control master for HOST if there is none: -f backgrounds it after the
# connection is up, ControlPersist ends it after five idle minutes, and its
# stdio is /dev/null so nothing of the caller's stays open behind it.
mux_host_master() {
  mux_host_ssh "$1" || return 1
  local -a base=("${MUX_HOST_SSH[@]:0:${#MUX_HOST_SSH[@]}-1}") target="${MUX_HOST_SSH[-1]}"
  "${base[@]}" -O check "$target" >/dev/null 2>&1 && return 0
  "${base[@]/ControlMaster=no/ControlMaster=yes}" -o ControlPersist=300 -fN "$target" </dev/null >/dev/null 2>&1
}
