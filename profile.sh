#!/usr/bin/env bash
# profile.sh -- the ACCOUNT PROFILE, resolved once and shared by everything.
#
# A profile is one Claude account: its config dir, its tmux session, its
# schedules, its backups, its handovers, its watchdog and its usage cache. It
# is named by the SUFFIX on the config dir, so the default account keeps every
# path it has always had:
#
#   CLAUDE_CONFIG_DIR unset / ~/.claude   ->  profile ""      suffix ""
#   ~/.claude-work                        ->  profile "work"  suffix "-work"
#
# THE EMPTY SUFFIX IS THE WHOLE MIGRATION. The default account's folders and
# its tmux session keep their original names; a second account gets siblings
# beside them. Nothing has to move, and no path already written down or typed
# from memory stops being true.
#
# Source it, do not run it:
#   . "$(dirname "$(readlink -f "$0")")/profile.sh"
#   echo "$MUX_PROFILE $MUX_SUFFIX $MUX_SCHEDULES"
#
# Every function also takes an explicit profile, because one process often has
# to ask about an account other than its own (the installer, `mux ls`, a
# health check that must report on every account rather than the current one).

# ------------------------------------------------------------------ config
# WHERE THE DATA LIVES is a setting, not a constant: this started life in a
# personal ~/.code and is published for people who reasonably expect XDG. The
# config file wins, then the environment, then the XDG default -- so an
# existing install keeps its paths by having them written down, and a fresh
# one is well behaved with no config file at all.
MUX_CONFIG="${MUXTOPUS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/muxtopus/config}"
# shellcheck disable=SC1090
[ -f "$MUX_CONFIG" ] && . "$MUX_CONFIG"

# The checkout these scripts live in. Resolved from this file's own location,
# so a symlinked or copied `mux` finds its siblings either way; the config file
# can pin it for an install that moved.
MUXTOPUS_DIR="${MUXTOPUS_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}"
MUXTOPUS_HOME="${MUXTOPUS_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/muxtopus}"
export MUXTOPUS_DIR MUXTOPUS_HOME

# ---------------------------------------------------------------- profiles
# A profile name from a config dir: ".claude" -> "", ".claude-work" -> "work".
mux_profile_of_dir() {
  local b="${1##*/}"
  b="${b#.claude}"
  b="${b#-}"
  b="${b#_}"
  printf '%s' "$b"
}

# The config dir for a profile name. "" is the default account.
mux_config_of() {
  local p="${1:-}"
  if [ -z "$p" ]; then printf '%s' "$HOME/.claude"
  else printf '%s' "$HOME/.claude-$p"; fi
}

# The path suffix for a profile: "" or "-work".
mux_suffix_of() {
  local p="${1:-}"
  [ -z "$p" ] && return 0
  printf -- '-%s' "$p"
}

# Every profile on this machine, one per line, default first (as an empty
# line). PRESENCE OF THE DIRECTORY IS THE OPT-IN: you add an account by
# creating ~/.claude-<name>, and nothing has to be registered anywhere. Editor
# and backup leftovers are skipped so a stray ~/.claude-work.bak never becomes
# a phantom account a daemon polls forever.
mux_profiles() {
  local d b p
  [ -d "$HOME/.claude" ] && echo ""
  for d in "$HOME"/.claude-*; do
    [ -d "$d" ] || continue
    b="${d##*/}"
    case "$b" in *.bak|*~|*.old|*.tmp) continue ;; esac
    p="$(mux_profile_of_dir "$d")"
    case "$p" in ''|*[!a-zA-Z0-9_-]*) continue ;; esac
    printf '%s\n' "$p"
  done
}

# Fill MUX_* for one profile. Called with no argument it resolves the profile
# of THIS process from CLAUDE_CONFIG_DIR, which is what a script running inside
# a session wants; a caller acting on another account passes the name.
mux_use_profile() {
  local p
  if [ $# -gt 0 ]; then
    p="$1"
  else
    p="$(mux_profile_of_dir "${CLAUDE_CONFIG_DIR:-$HOME/.claude}")"
  fi
  MUX_PROFILE="$p"
  MUX_SUFFIX="$(mux_suffix_of "$p")"
  MUX_CONFIG_DIR="$(mux_config_of "$p")"
  MUX_TMUX="${MUXTOPUS_SESSION_PREFIX:-claude}$MUX_SUFFIX"
  MUX_SCHEDULES="$MUXTOPUS_HOME/schedules$MUX_SUFFIX"
  MUX_BACKUPS="$MUXTOPUS_HOME/backups$MUX_SUFFIX"
  MUX_HANDOVERS="$MUXTOPUS_HOME/handovers$MUX_SUFFIX"
  MUX_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog$MUX_SUFFIX"
  MUX_UNIT="claude-watchdog$MUX_SUFFIX.service"
  # A label for anywhere a column or a log line has to name the account, where
  # an empty string would read as missing data rather than as the default one.
  MUX_LABEL="${p:-personal}"
  export MUX_PROFILE MUX_SUFFIX MUX_CONFIG_DIR MUX_TMUX \
         MUX_SCHEDULES MUX_BACKUPS MUX_HANDOVERS MUX_STATE MUX_UNIT MUX_LABEL
}

# Make an account's folders. Idempotent, and called on every session start:
# the handover folder in particular is written to by a wind-down, which is the
# worst possible moment to discover a missing directory.
mux_ensure_dirs() {
  mkdir -p "$MUX_SCHEDULES/templates" "$MUX_BACKUPS" "$MUX_HANDOVERS/done"
}

mux_use_profile
