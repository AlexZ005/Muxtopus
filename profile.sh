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
#   echo "$MUX_PROFILE $MUX_SUFFIX $MUX_SCHEDULES $WATCHDOG_SOFT_PCT"
#
# Every function also takes an explicit profile, because one process often has
# to ask about an account other than its own (the installer, `muxtopus ls`, a
# health check that must report on every account rather than the current one).

# ------------------------------------------------------------------ config
# WHERE THE DATA LIVES is a setting, not a constant: this started life in a
# personal ~/.code and is published for people who reasonably expect XDG.
#
# TWO LAYERS OF PLAIN SHELL, sourced:
#
#   ~/.config/muxtopus/config                 every account: paths, defaults
#   ~/.config/muxtopus/profiles/<name>.conf   one named account's overrides
#
# The same keys mean the same thing in both; the second file only narrows the
# scope. Precedence, lowest first: built-in default, environment, config,
# profile file -- so an existing install keeps its paths by having them
# written down, a fresh one is well behaved with no file at all, and one
# account can differ from the rest without touching the others.
#
# THERE IS NO REGISTRY OF PROFILES. An account exists because ~/.claude-<name>
# does (mux_profiles, below); its .conf is optional and describes it, it does
# not create it. A second list would only ever drift from the first.
#
# The default account has no name and no .conf: the shared file IS its
# configuration, and named accounts layer on top of that.
MUX_CONFIG="${MUXTOPUS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/muxtopus/config}"
MUX_PROFILES_DIR="${MUXTOPUS_PROFILES_DIR:-${MUX_CONFIG%/*}/profiles}"

# EVERY KEY A CONFIG FILE MAY SET, with its built-in default. ONE LIST, and
# muxconfig.py carries the same one, so the shell half and the python half
# honour exactly the same settings. A default of "-" means the reader computes
# it (the checkout from its own path, the model from settings.json).
MUX_CONFIG_KEYS="
MUXTOPUS_HOME=-
MUXTOPUS_DIR=-
MUXTOPUS_SESSION_PREFIX=claude
MUXTOPUS_QUESTIONS_DIR=-
WATCHDOG_INTERVAL=30
WATCHDOG_SOFT_PCT=65
WATCHDOG_HARD_PCT=85
WATCHDOG_FRESH_CTX=150000
WATCHDOG_LOWPRI_WEEK=40
WATCHDOG_USAGE_EVERY=60
WATCHDOG_USAGE_STALE=180
WATCHDOG_HEARTBEAT_LOG=60
WATCHDOG_STRANDED=120
CLAUDE_USAGE_MAX_AGE=20
CLAUDE_USAGE_MODEL=-
CLAUDE_CONTEXT_WINDOW=1000000
"

# The checkout these scripts live in, from this file's own location, so a
# symlinked or copied `muxtopus` finds its siblings either way.
_MUX_SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# THE ENVIRONMENT AS IT WAS before any file was read, for the keys above.
# Taken once per process, because a file's value must not be mistaken for the
# caller's on the second load (muxtopus -l asks about every account in turn).
if [ -z "${_MUX_ENV_TAKEN:-}" ]; then
  for _kv in $MUX_CONFIG_KEYS; do
    _k="${_kv%%=*}"
    [ -n "${!_k+x}" ] && printf -v "_MUX_ENV_$_k" '%s' "${!_k}"
  done
  _MUX_ENV_TAKEN=1
fi

# Load the layers for ONE account into this shell. Safe to call again for
# another account: the environment is put back first, so nothing set for the
# previous one leaks into the next.
mux_load_config() {
  local p="${1:-}" kv k v d
  for kv in $MUX_CONFIG_KEYS; do
    k="${kv%%=*}"; v="_MUX_ENV_$k"
    if [ -n "${!v+x}" ]; then printf -v "$k" '%s' "${!v}"; else unset "$k"; fi
  done
  # shellcheck disable=SC1090
  [ -f "$MUX_CONFIG" ] && . "$MUX_CONFIG"
  MUXTOPUS_DIR="${MUXTOPUS_DIR:-$_MUX_SELF_DIR}"
  MUXTOPUS_HOME="${MUXTOPUS_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/muxtopus}"
  MUX_SHARED_HOME="$MUXTOPUS_HOME"
  MUX_PROFILE_CONF=""
  if [ -n "$p" ]; then
    MUX_PROFILE_CONF="$MUX_PROFILES_DIR/$p.conf"
    # shellcheck disable=SC1090
    [ -f "$MUX_PROFILE_CONF" ] && . "$MUX_PROFILE_CONF"
  fi
  # THIS account's home may differ from the shared one; MUX_HOME carries it.
  # The exported MUXTOPUS_HOME keeps meaning the SHARED home, or a child
  # process asking about a different account would inherit this one's as its
  # baseline and put that account's folders in the wrong place.
  MUX_HOME="$MUXTOPUS_HOME"
  MUXTOPUS_HOME="$MUX_SHARED_HOME"
  for kv in $MUX_CONFIG_KEYS; do
    k="${kv%%=*}"; d="${kv#*=}"
    [ "$d" = "-" ] && continue
    [ -n "${!k:-}" ] || printf -v "$k" '%s' "$d"
  done
  export MUXTOPUS_DIR MUXTOPUS_HOME
  return 0
}

# What each key means, for the files this tool writes. Kept beside the key
# list rather than in it so the list stays parseable by a plain for-loop.
mux_key_help() {
  case "$1" in
    MUXTOPUS_HOME)          echo "Where schedules/, backups/ and handovers/ live."
                            echo "Default: \${XDG_DATA_HOME:-~/.local/share}/muxtopus. In a profile file"
                            echo "this is that account's OWN home, with the three folders unsuffixed." ;;
    MUXTOPUS_DIR)           echo "The checkout. Only needed when muxtopus is copied rather than"
                            echo "symlinked, so it cannot find its siblings by its own path." ;;
    MUXTOPUS_SESSION_PREFIX) echo "The tmux session name; a named account gets -<name> appended." ;;
    MUXTOPUS_QUESTIONS_DIR) echo "Where autonomous plan sessions park their questions (dashboard)." ;;
    WATCHDOG_INTERVAL)      echo "Seconds between watchdog passes." ;;
    WATCHDOG_SOFT_PCT)      echo "Wind-down bands, as % of the 5-hour session budget. At SOFT a working"
                            echo "window is asked to checkpoint; at HARD to stop, if that buys anything." ;;
    WATCHDOG_HARD_PCT)      echo "See WATCHDOG_SOFT_PCT." ;;
    WATCHDOG_FRESH_CTX)     echo "Context (tokens) above which a window is cheaper to restart from a"
                            echo "handoff than to carry on with." ;;
    WATCHDOG_LOWPRI_WEEK)   echo "Weekly % below which /low-priority is offered instead of waiting"
                            echo "for the session reset." ;;
    WATCHDOG_USAGE_EVERY)   echo "Minutes between the watchdog's /usage probes. Each starts a"
                            echo "throwaway claude process; none spends tokens." ;;
    WATCHDOG_USAGE_STALE)   echo "Minutes after which a budget READING is too old to fire a schedule's"
                            echo "'at: reset' fresh-budget gate. The reset epoch is exempt: it is an"
                            echo "absolute moment and stays true however old the row carrying it is." ;;
    WATCHDOG_HEARTBEAT_LOG) echo "Minutes between the watchdog's 'alive' log lines. The log otherwise"
                            echo "records only changes, so it cannot answer 'was it running at 4am'."
                            echo "0 turns it off; the heartbeat FILE is written every pass regardless." ;;
    WATCHDOG_STRANDED)      echo "Minutes a scheduled lane may sit idle with an OPEN handover and no"
                            echo "pending schedule entry naming it before its state becomes 'stranded'"
                            echo "instead of 'idle' -- nothing is ever going to touch that window."
                            echo "0 turns it off. It is a fact shown to a human, never a trigger." ;;
    CLAUDE_USAGE_MAX_AGE)   echo "Minutes: the dashboard's u and R re-read the limits only past this age." ;;
    CLAUDE_USAGE_MODEL)     echo "Which model's limit line the probe reads. Default: the model in"
                            echo "the account's settings.json." ;;
    CLAUDE_CONTEXT_WINDOW)  echo "Tokens the dashboard draws the context bar against." ;;
    *)                      echo "(undocumented)" ;;
  esac
}

# THE BODY OF A CONFIG FILE, with EVERY key present at its default and
# commented out, so a file shows what can be set without pinning anything:
# uncomment a line to set it, leave it and a future default still applies.
# Extra arguments KEY=VALUE are written live instead. One template for the
# installer, the Deck bootstrap and account creation, so they cannot drift.
#
#   mux_config_template ""     "MUXTOPUS_HOME=$HOME/.code"     > config
#   mux_config_template work   "MUXTOPUS_HOME=$HOME/work/.mx"  > profiles/work.conf
mux_config_template() {
  local p="${1:-}" kv k d a set val; shift
  if [ -z "$p" ]; then
    echo "# Muxtopus -- plain shell, sourced by profile.sh and read by muxconfig.py."
    echo "# EVERY account. profiles/<name>.conf beside this file overrides any key for"
    echo "# one account. A file wins over the environment, which wins over the built-in"
    echo "# defaults. Lines starting with # show the defaults; uncomment one to set it."
    echo "# \`muxtopus -c\` shows what is in effect."
  else
    echo "# Muxtopus -- the '$p' account (~/.claude-$p). Same keys as ../config; a key"
    echo "# set here applies to this account only. Lines starting with # show the"
    echo "# defaults; uncomment one to set it. \`muxtopus -c --profile=$p\` shows what"
    echo "# is in effect."
  fi
  for kv in $MUX_CONFIG_KEYS; do
    k="${kv%%=*}"; d="${kv#*=}"
    echo
    mux_key_help "$k" | sed 's/^/# /'
    set=""
    for a in "$@"; do [ "${a%%=*}" = "$k" ] && { set=1; val="${a#*=}"; }; done
    if [ -n "$set" ]; then printf '%s="%s"\n' "$k" "$val"
    elif [ "$d" = "-" ]; then echo "#$k="
    else echo "#$k=$d"
    fi
  done
}

# The effective configuration of one account, one setting per line with the
# layer it came from -- the answer to "which file is this reading".
mux_show_config() {
  local p="${1:-}" kv k v d src val
  mux_use_profile "$p"
  printf '%-24s %s\n' account "$MUX_LABEL"
  printf '%-24s %s\n' claude-config "$MUX_CONFIG_DIR"
  printf '%-24s %s\n' tmux-session "$MUX_TMUX"
  printf '%-24s %s%s\n' config "$MUX_CONFIG" "$([ -f "$MUX_CONFIG" ] || printf ' (absent)')"
  [ -n "$p" ] && printf '%-24s %s%s\n' profile-config "$MUX_PROFILE_CONF" \
                   "$([ -f "$MUX_PROFILE_CONF" ] || printf ' (absent)')"
  printf '%-24s %s\n' schedules "$MUX_SCHEDULES"
  printf '%-24s %s\n' backups "$MUX_BACKUPS"
  printf '%-24s %s\n' handovers "$MUX_HANDOVERS"
  printf '%-24s %s\n' watchdog-state "$MUX_STATE"
  echo
  for kv in $MUX_CONFIG_KEYS; do
    k="${kv%%=*}"; d="${kv#*=}"; v="_MUX_ENV_$k"
    if [ -n "$MUX_PROFILE_CONF" ] && grep -q "^[[:space:]]*$k=" "$MUX_PROFILE_CONF" 2>/dev/null; then src=profile
    elif grep -q "^[[:space:]]*$k=" "$MUX_CONFIG" 2>/dev/null; then src=config
    elif [ -n "${!v+x}" ]; then src=environment
    elif [ "$d" != "-" ]; then src=default
    else src="computed by the reader"
    fi
    val="${!k:-}"; [ "$k" = MUXTOPUS_HOME ] && val="$MUX_HOME"
    printf '%-24s %-34s %s\n' "$k" "${val:--}" "($src)"
  done
}

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
  mux_load_config "$p"
  MUX_PROFILE="$p"
  MUX_SUFFIX="$(mux_suffix_of "$p")"
  MUX_CONFIG_DIR="$(mux_config_of "$p")"
  MUX_TMUX="${MUXTOPUS_SESSION_PREFIX:-claude}$MUX_SUFFIX"
  # AN ACCOUNT MAY HAVE A HOME OF ITS OWN: MUXTOPUS_HOME in its profile file
  # puts its three folders somewhere else entirely -- next to that account's
  # repos, say. Inside a home that belongs to one account the folders are
  # UNSUFFIXED, because the suffix only ever existed to keep two accounts'
  # siblings apart in a shared one.
  if [ "$MUX_HOME" = "$MUX_SHARED_HOME" ]; then
    MUX_SCHEDULES="$MUX_HOME/schedules$MUX_SUFFIX"
    MUX_BACKUPS="$MUX_HOME/backups$MUX_SUFFIX"
    MUX_HANDOVERS="$MUX_HOME/handovers$MUX_SUFFIX"
  else
    MUX_SCHEDULES="$MUX_HOME/schedules"
    MUX_BACKUPS="$MUX_HOME/backups"
    MUX_HANDOVERS="$MUX_HOME/handovers"
  fi
  MUX_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog$MUX_SUFFIX"
  MUX_UNIT="claude-watchdog$MUX_SUFFIX.service"
  # A label for anywhere a column or a log line has to name the account, where
  # an empty string would read as missing data rather than as the default one.
  MUX_LABEL="${p:-personal}"
  export MUX_PROFILE MUX_SUFFIX MUX_CONFIG_DIR MUX_TMUX MUX_HOME MUX_PROFILE_CONF \
         MUX_SCHEDULES MUX_BACKUPS MUX_HANDOVERS MUX_STATE MUX_UNIT MUX_LABEL
}

# Put THIS account into the environment for anything launched from here.
#
# THE DEFAULT ACCOUNT IS THE VARIABLE BEING ABSENT, not the variable pointing
# at ~/.claude. Claude Code keeps the default account's onboarding and auth
# state in ~/.claude.json, but when CLAUDE_CONFIG_DIR is set it looks for
# <dir>/.claude.json instead -- and ~/.claude/.claude.json does not exist. So
# "helpfully" exporting the path the default account already uses shows a
# fully logged-in machine the theme picker and the login menu. Measured, not
# guessed: same binary, same folder, variable set vs unset.
#
# A named account has no such history: its config dir was created for it and
# holds its own .claude.json, so it needs the variable and gets it.
mux_export_config_dir() {
  if [ -n "${MUX_PROFILE:-}" ]; then
    export CLAUDE_CONFIG_DIR="$MUX_CONFIG_DIR"
  else
    unset CLAUDE_CONFIG_DIR
  fi
}

# The `tmux -e` arguments that carry this account into a NEW session or window,
# left in the array MUX_TMUX_ENV.
#
# EXPORTING IS NOT ENOUGH. A tmux session does not inherit the environment of
# the process that created it -- it starts from the server's, which belongs to
# whichever account happened to start the server first. Every `claude` opened
# under tmux therefore needs the account passed in explicitly, and the default
# account needs exactly nothing passed, for the reason above.
mux_tmux_env() {
  MUX_TMUX_ENV=()
  [ -n "${MUX_PROFILE:-}" ] && MUX_TMUX_ENV=(-e "CLAUDE_CONFIG_DIR=$MUX_CONFIG_DIR")
  return 0
}

# Make an account's folders. Idempotent, and called on every session start:
# the handover folder in particular is written to by a wind-down, which is the
# worst possible moment to discover a missing directory.
mux_ensure_dirs() {
  mkdir -p "$MUX_SCHEDULES/templates" "$MUX_BACKUPS" "$MUX_HANDOVERS/done"
}

mux_use_profile
