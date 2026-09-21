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
# FOUR LAYERS OF PLAIN SHELL, sourced -- two hand-written, two the dashboard
# writes (its Settings menu; the DASHBOARD_* keys):
#
#   ~/.config/muxtopus/config                           every account: paths, defaults
#   ~/.config/muxtopus/dashboard.conf                   every account, dashboard-written
#   ~/.config/muxtopus/profiles/<name>.conf             one named account's overrides
#   ~/.config/muxtopus/profiles/<name>.dashboard.conf   one account, dashboard-written
#
# The same keys mean the same thing in all of them; the per-account files only
# narrow the scope. Precedence, lowest first: built-in default, environment,
# config, dashboard.conf, profile file, profile dashboard file -- so an
# existing install keeps its paths by having them written down, a fresh one is
# well behaved with no file at all, one account can differ from the rest
# without touching the others, and what the dashboard's menu writes is what
# is read next (muxsettings.py says why it sits above the hand-written file).
#
# THERE IS NO REGISTRY OF PROFILES. An account exists because ~/.claude-<name>
# does (mux_profiles, below); its .conf is optional and describes it, it does
# not create it. A second list would only ever drift from the first.
#
# The default account has no name and no .conf: the shared file IS its
# configuration, and named accounts layer on top of that.
MUX_CONFIG="${MUXTOPUS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/muxtopus/config}"
MUX_PROFILES_DIR="${MUXTOPUS_PROFILES_DIR:-${MUX_CONFIG%/*}/profiles}"
# THE FILE THE DASHBOARD WRITES (muxsettings.py), read as a layer above the
# hand-written file at the same scope: `config` is the user's, full of their
# comments, and a program rewriting it would eventually eat them. Sourced
# right after `config`; the per-account one right after the profile file.
MUX_CONFIG_DASH="${MUX_CONFIG%/*}/dashboard.conf"

# EVERY KEY A CONFIG FILE MAY SET, with its built-in default. ONE LIST, and
# muxconfig.py carries the same one, so the shell half and the python half
# honour exactly the same settings. A default of "-" means the reader computes
# it (the checkout from its own path, the model from settings.json).
MUX_CONFIG_KEYS="
MUXTOPUS_HOME=-
MUXTOPUS_DIR=-
MUXTOPUS_PYTHON=-
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
WATCHDOG_WOUND_RESUME=on
CLAUDE_USAGE_MAX_AGE=20
CLAUDE_USAGE_MODEL=-
CLAUDE_CONTEXT_WINDOW=1000000
DASHBOARD_MENU_LAYOUT=modal
DASHBOARD_NEW_PERMISSION_MODE=ask
DASHBOARD_PERMANENT_MODE_SCOPE=project
DASHBOARD_NEW_WATCHDOG=on
DASHBOARD_NEW_MONITOR=on
DASHBOARD_NEW_MODEL=-
DASHBOARD_NEW_EFFORT=-
DASHBOARD_NEW_CWD=-
MUXTOPUS_NOTIFY_WAITING=on
MUXTOPUS_NOTIFY_QUESTIONS=on
MUXTOPUS_NOTIFY_TROUBLE=on
MUXTOPUS_NOTIFY_BLOCKED_AFTER=120
MUXTOPUS_NOTIFY_DONE=on
MUXTOPUS_NOTIFY_INBOUND=on
MUXTOPUS_NOTIFY_PANE_TEXT=on
DASHBOARD_HANDOVERS_DONE=off
DASHBOARD_HANDOVERS_QUESTIONS=on
MUXTOPUS_NOTIFY_SESSION=on
MUXTOPUS_NOTIFY_AUTH=on
MUXTOPUS_NOTIFY_LIMIT=on
MUXTOPUS_NOTIFY_LIMIT_BANDS=off
MUXTOPUS_NOTIFY_STALLED=on
MUXTOPUS_NOTIFY_STRANDED=on
DASHBOARD_NEW_RC=off
DASHBOARD_TABS_HIDDEN=-
WATCHDOG_RESTORE=ask
WATCHDOG_RESTORE_MAX_AGE=24
MUXTOPUS_TMUX_SOCKET=default
MUXTOPUS_UPDATE_MODE=notify
MUXTOPUS_UPDATE_EVERY=24
MUXTOPUS_UPDATE_CHANNEL=stable
MUXTOPUS_NOTIFY_UPDATE=off
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
  # shellcheck disable=SC1090
  [ -f "$MUX_CONFIG_DASH" ] && . "$MUX_CONFIG_DASH"
  MUXTOPUS_DIR="${MUXTOPUS_DIR:-$_MUX_SELF_DIR}"
  MUXTOPUS_HOME="${MUXTOPUS_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/muxtopus}"
  MUX_SHARED_HOME="$MUXTOPUS_HOME"
  MUX_PROFILE_CONF=""
  MUX_PROFILE_DASH=""
  if [ -n "$p" ]; then
    MUX_PROFILE_CONF="$MUX_PROFILES_DIR/$p.conf"
    MUX_PROFILE_DASH="$MUX_PROFILES_DIR/$p.dashboard.conf"
    # shellcheck disable=SC1090
    [ -f "$MUX_PROFILE_CONF" ] && . "$MUX_PROFILE_CONF"
    # shellcheck disable=SC1090
    [ -f "$MUX_PROFILE_DASH" ] && . "$MUX_PROFILE_DASH"
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
  # WHERE THE UPDATE CHECK KEEPS ITS ANSWER. Not under MUX_STATE, which is
  # per account: there is ONE installed tree, so two accounts asking GitHub
  # the same question twice a day is two answers that can disagree about what
  # is installed. One directory, no suffix, whoever gets there first writes
  # it -- mux-update.sh --check returns at once when it is fresh.
  MUX_UPDATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/muxtopus-update"
  mux_resolve_python
  export MUXTOPUS_DIR MUXTOPUS_HOME MUX_UPDATE_DIR
  return 0
}

# SET FROM THE MOMENT THIS FILE IS SOURCED, so a caller that reads it before
# loading an account's config -- `muxtopus stats` does, deliberately -- has a
# command to run rather than an unset variable under `set -u`.
MUX_PYTHON="${MUX_PYTHON:-python3}"

# THE INTERPRETER THE PYTHON HALF RUNS ON, in MUX_PYTHON.
#
# `python3` used to be typed into every call site, which is right on a machine
# that has a new enough one and wrong on the machine this exists for: the
# installer can now fetch a standalone CPython into the data home when the
# system has none, or has 3.9 (see install.sh, "Python"). That interpreter is
# deliberately NOT on PATH -- it is muxtopus's, not the machine's, and putting
# a python3 of our choosing in front of the user's own tools is not a thing an
# installer should do -- so the only way it ever gets used is by being named
# here, once, and read from MUX_PYTHON everywhere else.
#
# IN ORDER: what the config pins, the embedded one where the installer puts
# it, the venv beside the checkout (which is a real interpreter with rich in
# it), then whatever `python3` means on PATH. EACH ONE IS PROBED rather than
# merely found, because the failure this has to survive is an OS update that
# moves Python and leaves an executable venv symlink behind pointing at
# nothing -- and a dashboard that cannot start is the one thing worse than a
# dashboard without colours.
#
# ONCE PER PROCESS (_MUX_PY_TAKEN): the answer does not depend on the account,
# and `muxtopus -l` loads the config for every account in turn.
mux_resolve_python() {
  [ -n "${_MUX_PY_TAKEN:-}" ] && return 0
  local c
  for c in "${MUXTOPUS_PYTHON:-}" \
           "${MUXTOPUS_HOME:-}/python/bin/python3" \
           "${MUXTOPUS_DIR:-}/.venv/bin/python" \
           python3; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || continue
    MUX_PYTHON="$c"
    _MUX_PY_TAKEN=1
    export MUX_PYTHON
    return 0
  done
  # Nothing usable. `python3` is still the honest answer -- the caller's own
  # error message ("no python3") is better than an empty command line -- and
  # every caller of this already degrades when the python half will not run.
  MUX_PYTHON=python3
  _MUX_PY_TAKEN=1
  export MUX_PYTHON
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
    MUXTOPUS_PYTHON)        echo "The python3 the dashboard, stats and notifications run on. Set by"
                            echo "install.sh when it had to fetch one (no python3 >= 3.10 here);"
                            echo "unset means: the embedded one under MUXTOPUS_HOME, the venv beside"
                            echo "the checkout, or python3 from PATH, whichever works." ;;
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
    WATCHDOG_WOUND_RESUME)  echo "on|off. A window wound down at the HARD band was told to stop, so it"
                            echo "never prints the limit banner the resume path watches for. With this"
                            echo "on, such a window is sent the continue message once its budget window"
                            echo "has come back -- but only while its handover is still open, and never"
                            echo "if it is opted out. off is the behaviour before this existed: the"
                            echo "window stops and nothing restarts it." ;;
    CLAUDE_USAGE_MAX_AGE)   echo "Minutes: the dashboard's u and R re-read the limits only past this age." ;;
    CLAUDE_USAGE_MODEL)     echo "Which model's limit line the probe reads. Default: the model in"
                            echo "the account's settings.json." ;;
    CLAUDE_CONTEXT_WINDOW)  echo "Tokens the dashboard draws the context bar against." ;;
    # The dashboard's own, normally written by its Settings menu (esc) into
    # dashboard.conf beside this file, which wins over a value set here.
    DASHBOARD_MENU_LAYOUT)  echo "How the dashboard draws a context menu: table (under the panel the"
                            echo "cursor is in), modal (centred) or bottom (the footer, scrolling)." ;;
    DASHBOARD_NEW_PERMISSION_MODE) echo "Permission mode preselected when the dashboard's c creates a window:"
                            echo "ask, or one of acceptEdits auto bypassPermissions manual dontAsk plan." ;;
    DASHBOARD_PERMANENT_MODE_SCOPE) echo "Which settings.json 'make it the default' writes: project"
                            echo "(<cwd>/.claude/settings.json) or account (~/.claude/settings.json)." ;;
    DASHBOARD_NEW_WATCHDOG) echo "on: a window the dashboard creates is restarted after a limit;"
                            echo "off: the entry carries watchdog: off and the launcher opts it out." ;;
    DASHBOARD_NEW_MONITOR)  echo "on: a window the dashboard creates may be wound down near the limit;"
                            echo "off: the entry carries monitor: off and the launcher opts it out." ;;
    DASHBOARD_NEW_MODEL)    echo "Model alias preselected for a new window (opus, fable, sonnet…);"
                            echo "empty is the account default, no --model flag." ;;
    DASHBOARD_NEW_EFFORT)   echo "Effort preselected for a new window (low medium high xhigh max);"
                            echo "empty is the account default, no --effort flag." ;;
    DASHBOARD_NEW_CWD)      echo "Working folder offered first when the dashboard creates a window or"
                            echo "a schedule entry; empty falls back to the selected session's cwd." ;;
    DASHBOARD_TABS_HIDDEN)  echo "Tabs hidden from the dashboard's strip and from ←→, by view name,"
                            echo "comma-separated (handovers). esc > Settings > Tabs writes it." ;;
    # Phone notifications (claude-notify.sh + muxtelegram.py). These are
    # PREFERENCES and live here, per account; the backend and its token live
    # in ~/.config/claude-notify.conf, which is per machine and holds a
    # secret. The dashboard writes these from esc > Settings > Notifications.
    MUXTOPUS_NOTIFY_WAITING) echo "on: tell the phone when a window sits at a permission or trust"
                            echo "prompt (seen on two consecutive passes, so >=30 s, not a flash)."
                            echo "The message carries Yes / No / More when inbound is on." ;;
    MUXTOPUS_NOTIFY_QUESTIONS) echo "on: tell the phone when a QUESTIONS file is new or has a new"
                            echo "unanswered fork. One message per fork, capped at eight." ;;
    MUXTOPUS_NOTIFY_TROUBLE) echo "on: tell the phone when an entry is marked error (a launch failed)"
                            echo "or has been blocked longer than MUXTOPUS_NOTIFY_BLOCKED_AFTER."
                            echo "Stalled and stranded have switches of their own (below)." ;;
    MUXTOPUS_NOTIFY_BLOCKED_AFTER) echo "Minutes an entry may be blocked before that counts as trouble."
                            echo "Plain blocked is ordinary waiting; 0 never says it." ;;
    MUXTOPUS_NOTIFY_DONE)   echo "on: tell the phone when a handover reaches done/ -- its gist, and"
                            echo "the entries that were released by it." ;;
    MUXTOPUS_NOTIFY_INBOUND) echo "on: attach buttons and obey what comes back -- answering a prompt,"
                            echo "answering a fork, and the bot's own commands (/status, /pending,"
                            echo "/questions, /blocked, /windows, /stats, /mute). Off, the bot only"
                            echo "talks. Only the configured chat is ever obeyed." ;;
    MUXTOPUS_NOTIFY_PANE_TEXT) echo "on: a waiting message quotes the prompt box, and More sends the"
                            echo "lines above it. That text leaves this machine for the backend's"
                            echo "servers; off, a message names the window and nothing else." ;;
    # THE ALERTS. Each is told ONCE when it starts and once more, as
    # "cleared", when it ends. On by default: the ones where every lane can
    # silently stop. Off: the budget bands, which are news, not trouble.
    MUXTOPUS_NOTIFY_SESSION) echo "on: tell the phone when a pane that carried a claude session no"
                            echo "longer does while its window is still open (the process exited,"
                            echo "the pane is back at a shell). Seen on two passes, not a restart." ;;
    MUXTOPUS_NOTIFY_AUTH)   echo "on: tell the phone when the account stops being logged in: the"
                            echo "/usage probe finds the login screen, a pane shows an auth error"
                            echo "or a login prompt, or the credentials file is gone." ;;
    MUXTOPUS_NOTIFY_LIMIT)  echo "on: tell the phone when a budget is at its limit -- a limit"
                            echo "banner in a pane, or a reading at 100% -- naming the budget"
                            echo "(session, week, the model's week) and when it resets." ;;
    MUXTOPUS_NOTIFY_LIMIT_BANDS) echo "on: also tell the phone when a budget crosses"
                            echo "WATCHDOG_SOFT_PCT or WATCHDOG_HARD_PCT. Off by default: a band"
                            echo "is a forecast the watchdog already acts on, not trouble." ;;
    MUXTOPUS_NOTIFY_STALLED) echo "on: tell the phone when a schedule entry cannot be judged at"
                            echo "all (verdict stalled in sched-why.tsv), and when it recovers." ;;
    MUXTOPUS_NOTIFY_STRANDED) echo "on: tell the phone when a lane is stranded -- idle with an open"
                            echo "handover and nothing that will ever resume it -- and when not." ;;
    DASHBOARD_NEW_RC)       echo "on: the launcher sends /rc to every new scheduled window once it"
                            echo "is ready, unless its entry says rc: off. An entry's rc: on|off"
                            echo "always wins; this is the default for entries that do not say." ;;
    WATCHDOG_RESTORE)       echo "What muxtopus does with a frozen window snapshot (docs/restore.md)."
                            echo "ask: offer it at a terminal when there is no session; auto: restore"
                            echo "without asking, and the watchdog relaunches muxtopus -d when the"
                            echo "server disappears; off: never offer (muxtopus --restore still works)." ;;
    WATCHDOG_RESTORE_MAX_AGE) echo "Hours. A frozen snapshot older than this is not offered at start;"
                            echo "muxtopus --restore takes it regardless." ;;
    MUXTOPUS_TMUX_SOCKET)   echo "The tmux server every muxtopus command talks to: a name (tmux -L),"
                            echo "or an absolute path (tmux -S). Passed EXPLICITLY on every call, so a"
                            echo "command run from inside a pane never follows that pane's \$TMUX to"
                            echo "some other server. default = what a bare tmux uses outside tmux." ;;
    # UPDATES (mux-update.sh, docs/updates.md). ONE INSTALL, SHARED BY EVERY
    # ACCOUNT: the code these keys govern is a single tree, so the dashboard
    # writes them to the shared dashboard.conf whatever account it is showing.
    MUXTOPUS_UPDATE_MODE)   echo "What muxtopus does about a new release. notify: check on a slow"
                            echo "clock and say so on the dashboard; nothing is downloaded until you"
                            echo "say yes. download: also fetch and stage it, so applying it is"
                            echo "local. off: never check, and never reach the network for this." ;;
    MUXTOPUS_UPDATE_EVERY)  echo "Hours between release checks. One HTTPS request that follows the"
                            echo "releases/latest redirect -- no API token, nothing about this"
                            echo "machine sent. The check is SHARED: whichever account's watchdog"
                            echo "gets there first does it, and the others read its answer." ;;
    MUXTOPUS_UPDATE_CHANNEL) echo "stable: the newest full release. prerelease: also pick up release"
                            echo "candidates, for a machine you dogfood your own tags on." ;;
    MUXTOPUS_NOTIFY_UPDATE) echo "on: tell the phone when a new muxtopus release is out, with the"
                            echo "headline of its notes. Off by default: it is news, not trouble." ;;
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
  printf '%-24s %s%s\n' dashboard-config "$MUX_CONFIG_DASH" "$([ -f "$MUX_CONFIG_DASH" ] || printf ' (absent)')"
  [ -n "$p" ] && printf '%-24s %s%s\n' profile-config "$MUX_PROFILE_CONF" \
                   "$([ -f "$MUX_PROFILE_CONF" ] || printf ' (absent)')"
  printf '%-24s %s\n' schedules "$MUX_SCHEDULES"
  printf '%-24s %s\n' backups "$MUX_BACKUPS"
  printf '%-24s %s\n' handovers "$MUX_HANDOVERS"
  printf '%-24s %s\n' watchdog-state "$MUX_STATE"
  echo
  for kv in $MUX_CONFIG_KEYS; do
    k="${kv%%=*}"; d="${kv#*=}"; v="_MUX_ENV_$k"
    if [ -n "$MUX_PROFILE_DASH" ] && grep -q "^[[:space:]]*$k=" "$MUX_PROFILE_DASH" 2>/dev/null; then src=profile-dashboard
    elif [ -n "$MUX_PROFILE_CONF" ] && grep -q "^[[:space:]]*$k=" "$MUX_PROFILE_CONF" 2>/dev/null; then src=profile
    elif grep -q "^[[:space:]]*$k=" "$MUX_CONFIG_DASH" 2>/dev/null; then src=dashboard
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
  mux_tmux_socket
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
  export MUX_PROFILE MUX_SUFFIX MUX_CONFIG_DIR MUX_TMUX MUX_HOME MUX_PROFILE_CONF MUX_PROFILE_DASH \
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

# THE ONE WAY TO TALK TO TMUX. Every tmux call in muxtopus, the watchdog, the
# usage probe and the test sandbox goes through here, and the socket is named
# on every call: -L <name> or -S <path> from MUXTOPUS_TMUX_SOCKET.
#
# WHY IT MUST BE EXPLICIT. tmux picks its server in this order: -S, -L, then
# $TMUX, then TMUX_TMPDIR/tmux-<uid>/default. Inside a pane $TMUX is always
# set, so a bare `tmux` there reaches the server of THAT pane whatever
# TMUX_TMPDIR says -- and on 2026-09-19 a `TMUX_TMPDIR=$SB/sock tmux
# kill-server` meant to clean a test sandbox killed the real server, with the
# dashboard, every lane window and five Claude sessions in it. With -L or -S
# given, $TMUX is not consulted at all: the sandbox's server and the real one
# are two different ARGUMENTS rather than two different environments, and a
# command cannot land on a server it did not name.
#
# The default name is `default`, which resolves to exactly the socket a bare
# tmux uses outside tmux (TMUX_TMPDIR/tmux-<uid>/default), so nothing changes
# for anyone who never set the key.
mux_tmux_socket() {
  local s="${MUXTOPUS_TMUX_SOCKET:-default}"
  case "$s" in
    /*) MUX_TMUX_SOCK=(-S "$s") ;;
    *)  MUX_TMUX_SOCK=(-L "$s") ;;
  esac
}
mux_tmux() { command tmux "${MUX_TMUX_SOCK[@]}" "$@"; }
# For the two places that hand the process over to tmux (attach, switch).
mux_tmux_exec() { exec tmux "${MUX_TMUX_SOCK[@]}" "$@"; }

# WHERE A WATCHDOG STARTED WITHOUT SYSTEMD LEAVES ITS PID FILE. XDG_RUNTIME_DIR
# when it is OURS: `su user` (no dash) hands the new user root's environment,
# XDG_RUNTIME_DIR=/run/user/0 included, and every write there is "Permission
# denied" -- measured on a fresh Ubuntu 25.04 box. Unset (`su - user`, a
# container, cron) this used to fall back to /tmp itself, where the second
# user's pid file is the first user's and the sticky bit makes it unwritable.
# So: a directory of our own under /tmp, per uid and 0700. The state dir is the
# last resort, because a pid file that survives a reboot can name a process
# that is now something else; the caller checks what the pid IS before trusting
# it (muxtopus, watchdog_up).
mux_run_dir() {
  local d="${XDG_RUNTIME_DIR:-}"
  if [ -n "$d" ] && [ -d "$d" ] && [ -O "$d" ] && [ -w "$d" ]; then
    printf '%s\n' "$d"; return 0
  fi
  d="${TMPDIR:-/tmp}/muxtopus-$(id -u)"
  mkdir -p -m 700 "$d" 2>/dev/null
  if [ -d "$d" ] && [ -O "$d" ] && [ -w "$d" ]; then
    printf '%s\n' "$d"; return 0
  fi
  mkdir -p "$MUX_STATE" 2>/dev/null
  printf '%s\n' "$MUX_STATE"
}

# Make an account's folders. Idempotent, and called on every session start:
# the handover folder in particular is written to by a wind-down, which is the
# worst possible moment to discover a missing directory.
mux_ensure_dirs() {
  mkdir -p "$MUX_SCHEDULES/templates" "$MUX_BACKUPS" "$MUX_HANDOVERS/done"
}

mux_use_profile
