#!/usr/bin/env bash
# profile.sh -- the ACCOUNT PROFILE, resolved once and shared by everything.
#
# A profile is one Claude account: its config dir, its tmux session, its
# schedules, its backups and its handovers. It is named by the SUFFIX on the
# config dir, so the default account keeps every path it has always had:
#
#   CLAUDE_CONFIG_DIR unset / ~/.claude   ->  profile ""      suffix ""
#   ~/.claude-work                        ->  profile "work"  suffix "-work"
#
# THE EMPTY SUFFIX IS THE WHOLE MIGRATION. ~/.code/schedules, ~/.code/backups
# and the tmux session `claude` are exactly where they were; a second account
# gets siblings beside them. Nothing has to move and no existing path in any
# README, dashboard help text or muscle memory stops being true.
#
# Source it, do not run it:
#   . "$HOME/.code/scripts/profile.sh"
#   echo "$CODE_PROFILE $CODE_SUFFIX $CODE_SCHEDULES"
#
# Every function also takes an explicit profile, because the watchdog is ONE
# daemon covering ALL of them and must ask about accounts other than its own.

# A profile name from a config dir: ".claude" -> "", ".claude-work" -> "work".
code_profile_of_dir() {
  local b="${1##*/}"
  b="${b#.claude}"
  b="${b#-}"
  b="${b#_}"
  printf '%s' "$b"
}

# The config dir for a profile name. "" is the default account.
code_config_of() {
  local p="${1:-}"
  if [ -z "$p" ]; then printf '%s' "$HOME/.claude"
  else printf '%s' "$HOME/.claude-$p"; fi
}

# The path suffix for a profile: "" or "-work".
code_suffix_of() {
  local p="${1:-}"
  [ -z "$p" ] && return 0
  printf -- '-%s' "$p"
}

# Every profile present on this machine, one per line, default first (as an
# empty line). PRESENCE OF THE DIRECTORY IS THE OPT-IN: you enable a second
# account by creating ~/.claude-<name>, and nothing else has to be registered.
# Backups and editor leftovers are skipped so a stray ~/.claude-work.bak never
# becomes a phantom account the watchdog polls forever.
code_profiles() {
  local d b p
  [ -d "$HOME/.claude" ] && echo ""
  for d in "$HOME"/.claude-*; do
    [ -d "$d" ] || continue
    b="${d##*/}"
    case "$b" in *.bak|*~|*.old|*.tmp) continue ;; esac
    p="$(code_profile_of_dir "$d")"
    case "$p" in ''|*[!a-z0-9_-]*) continue ;; esac
    printf '%s\n' "$p"
  done
}

# Fill CODE_* for one profile. Called with no argument it resolves the profile
# of THIS process from CLAUDE_CONFIG_DIR, which is what a script running inside
# a session wants; the watchdog passes a name instead.
code_use_profile() {
  local p
  if [ $# -gt 0 ]; then
    p="$1"
  else
    p="$(code_profile_of_dir "${CLAUDE_CONFIG_DIR:-$HOME/.claude}")"
  fi
  CODE_PROFILE="$p"
  CODE_SUFFIX="$(code_suffix_of "$p")"
  CODE_CONFIG_DIR="$(code_config_of "$p")"
  CODE_TMUX="claude$CODE_SUFFIX"
  CODE_SCHEDULES="$HOME/.code/schedules$CODE_SUFFIX"
  CODE_BACKUPS="$HOME/.code/backups$CODE_SUFFIX"
  CODE_HANDOVERS="$HOME/.code/handovers$CODE_SUFFIX"
  # A label for anywhere a column or a log line has to say WHICH account, where
  # an empty string would read as missing data rather than as the default one.
  CODE_LABEL="${p:-personal}"
  export CODE_PROFILE CODE_SUFFIX CODE_CONFIG_DIR CODE_TMUX \
         CODE_SCHEDULES CODE_BACKUPS CODE_HANDOVERS CODE_LABEL
}

code_use_profile
