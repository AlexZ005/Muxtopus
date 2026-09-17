#!/usr/bin/env bash
# THE ROUTE: every screen the dashboard can draw, photographed.
#
# Taken against the UNTOUCHED code first (phase 0) and reproduced byte for
# byte by every phase after it. A diff is a bug in the move, never a golden
# to regenerate.
#
# EVERY SHOT IS ASSERTED. `shot <name> <substring>` fails the route if the
# screen is not the one the route thinks it is on. Without that a key count
# that goes wrong by one silently photographs the previous screen twice, and
# the goldens then prove nothing about the screen nobody reached -- which is
# how the first draft of this file managed to capture the esc menu four times
# and call it the new-session flow.
#
# EACH FLOW STARTS FROM A FRESH DASHBOARD. Restarting costs two seconds and
# buys independence: a flow that breaks cannot poison the ones after it, and
# the route can be read as a list of scenarios rather than one long path.
#
# What is deliberately NOT here, and why:
#   p (btop), and Check on an entry (claude-watchdog.sh --check)  -- another
#     program's output, not this dashboard's frame.
#   enter on the desktop-extras row  -- it runs deck-ram.sh against the REAL
#     machine, which a test may not do.
#   u / U  -- they fork claude-usage.sh, which starts a claude session.
#   enter on continue/skip/save in the options table, and y on a delete
#     confirm  -- they write or remove fixture files; the create flow's file
#     name carries the wall clock, so it cannot be a golden anyway. What each
#     one DOES is tests/test_entry_options.py's subject, not a picture's.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"

CAPS="${SB:?}/caps"
rm -rf -- "${CAPS:?}"; mkdir -p -- "${CAPS:?}"
"$HERE/clean.sh"

K="$HERE/k.sh"; C="$HERE/cap.sh"; T="$HERE/type.sh"
fails=0

shot() {   # shot <name> <substring the screen must contain>
  "$C" > "${CAPS:?}/$1.txt"
  if ! grep -qF -- "$2" "${CAPS:?}/$1.txt"; then
    echo "ROUTE LOST: $1 does not contain '$2'" >&2
    sed -n '1,200p' "${CAPS:?}/$1.txt" | grep -v '^$' | tail -12 >&2
    fails=$((fails + 1))
  fi
}

layout() {   # write a menu layout into the fake machine's settings file
  local l="$1" f="${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"
  sed -i "s|^DASHBOARD_MENU_LAYOUT=.*|DASHBOARD_MENU_LAYOUT=\"$l\"|" -- "$f"
}

# ============================================================ the menus
# Every layout at every height. The reported bug was a menu clipped by the
# terminal, so the menus are the part measured at three heights.
for H in 24 40 58; do
  for L in table modal bottom; do
    layout "$L"
    "$HERE/start.sh" "$H" >/dev/null
    # At 24 rows the footer is off the bottom, so the marker is the panel
    # every height shows rather than the key line.
    shot "$H-$L-main"              "claude [mxsplit]"
    $K Space
    shot "$H-$L-session-top"       "Restart ➥root-lane after a limit"
    for i in 1 2 3 4 5 6 7 8; do PAUSE=0.12 $K Down; done
    sleep 0.4
    shot "$H-$L-session-scrolled"  "esc close"
    $K Escape
    $K Escape
    shot "$H-$L-mux"               "Disconnect"
    $K Enter
    shot "$H-$L-settings"          "Menu layout"
    $K Escape
    shot "$H-$L-settings-back"     "Disconnect"
    $K Escape
    $K s
    shot "$H-$L-sched"             "scheduled windows"
    $K Space
    shot "$H-$L-sched-menu"        "Edit a-pending.md"
    "$HERE/stop.sh"
  done
done

layout table

# ============================================== the main view's own keys
"$HERE/start.sh" 58 >/dev/null
shot "main"                   "➥root-lane"
$K t;    shot "main-tree-off" "tree off: sessions by context"
$K t;    shot "main-tree-on"  "children under their parent"
$K f;    shot "main-lanes-all" "lanes: every account"
$K f;    shot "main-lanes-mine" "lanes: mxsplit only"
$K Left; shot "main-folded"   "collapsed ➥root-lane"
$K Right; shot "main-unfolded" "expanded ➥root-lane"
$K Down; shot "main-cursor-second" "➥➥kid-lane"
$K Down; $K Down; $K Down; $K Down
shot "main-cursor-last"       "➥opted-out"
$K Down; shot "main-cursor-extras" "enter reclaims"
$K Space; shot "menu-extras"  "Reclaim or start desktop extras"
$K Escape
$K Up; $K Up; $K Up; $K Up; $K Up; $K Up; $K Up
shot "main-cursor-lane"       "enter: all"
$K Space; shot "menu-lane-row" "Show every account's lanes"
$K Escape
"$HERE/stop.sh"

# ====================================== the esc menu and every setting
"$HERE/start.sh" 58 >/dev/null
$K Escape;  shot "mux-menu"            "Quit the dashboard"
$K Down;    shot "mux-menu-watchdog"   "Watchdog: ON"
$K Enter;   shot "mux-menu-watchdog-off" "watchdog off"
$K Enter;   shot "mux-menu-watchdog-on"  "watchdog on"
$K Up;      $K Enter
shot "settings"                        "Default working folder"
$K Enter;   shot "settings-layout-picker" "bottom"
$K Escape;  shot "settings-layout-cancelled" "Menu layout: table"
$K Down; $K Down; $K Down
$K Enter;   shot "settings-watchdog-toggled" "Watch a new window: ON"
$K Down; $K Down; $K Down; $K Down
$K Enter;   shot "settings-cwd-prompt"  "Default working folder:"
$T "/nope"
$K Enter;   shot "settings-cwd-refused" "not a directory"
$K Escape;  shot "settings-esc-to-mux"  "Disconnect"
$K Escape;  shot "settings-closed"      "q quit"
"$HERE/stop.sh"

# ============================================ c: a new claude session
"$HERE/start.sh" 58 >/dev/null
$K c;      shot "new-folder"  "new session · working folder"
$K Enter;  shot "new-model"   "new session · model"
$K Enter;  shot "new-effort"  "new session · effort"
$K Enter;  shot "new-mode"    "nothing preselected"
$K Down; $K Down; $K Down
shot "new-mode-bypass"        "bypassPermissions"
$K Enter;  shot "new-bypass"  "…and make it the default"
$K Down;   shot "new-bypass-permanent" "writes settings.json"
$K Up
$K Enter;  shot "new-where"   "under ➥root-lane"
$K Down;   shot "new-where-under" "under ➥root-lane"
$K Up
$K Enter;  shot "new-name"    "new session · name"
$K BSpace; $K BSpace; $K BSpace; $K BSpace; $K BSpace; $K BSpace
$T "route-lane"
shot "new-name-typed"         "route-lane"
$K Enter;  shot "new-prompt"  "new session · first prompt"
$K Escape; shot "new-cancelled" "cancelled"
"$HERE/stop.sh"

# ================================================= ? the help screen
"$HERE/start.sh" 58 >/dev/null
$K "?";    shot "help"        "RAM is summed per PROCESS GROUP"
$K q
"$HERE/stop.sh"

# ============================================== the schedules view
"$HERE/start.sh" 58 >/dev/null
$K s;      shot "sched"       "a pending plan"
shot "sched-why-pending"      "not fresh yet"
$K Space;  shot "sched-menu-pending" "Launch now"
$K Escape
$K Down;   shot "sched-why-blocked" "waiting for lane root-lane"
$K Space;  shot "sched-menu-blocked" "Duplicate as a new pending entry"
$K Escape
$K Down;   shot "sched-why-corrupted" "will never launch"
$K Space;  shot "sched-menu-corrupted" "corrupted"
$K Escape
$K Down;   shot "sched-why-launched" "handover open"
$K Space;  shot "sched-menu-launched" "Open its window"
$K Escape
$K Down;   shot "sched-why-pinned" "no verdict yet"
$K Down;   shot "sched-why-options" "3 option(s)"
$K Space;  shot "sched-menu-options" "Options  the checkbox table"
$K Escape
# The keys the schedule view deliberately swallows.
$K Left; $K Right; $K t
shot "sched-swallowed"        "with options and a model"
$K r;      shot "sched-reloaded" "schedules re-read"
$K Escape; shot "sched-left"  "q quit"
"$HERE/stop.sh"

# ================================= o: the options table on an entry
"$HERE/start.sh" 58 >/dev/null
$K s
$K Down; $K Down; $K Down; $K Down; $K Down
$K o;      shot "options-reopen"  "save  what is ticked"
$K Down; $K Down
shot "options-moved"             "no push, no PR"
$K Space;  shot "options-toggled" "[x] no push, no PR"
# lanes and model arrive TICKED, from the entry's own header (lanes=3,
# model: fable), so each needs an untick before the value screen it owns
# can be reached -- which is itself the round trip worth photographing.
$K Down;   shot "options-on-lanes" "[x] parallel lanes: 3"
$K Space;  shot "options-lanes-unticked" "[ ] parallel lanes"
$K Space;  shot "options-ask-prompt" "parallel lanes: _"
$T "7"
$K Enter;  shot "options-ask-answered" "[x] parallel lanes: 7"
$K Down;   shot "options-on-model" "[x] model: fable"
$K Space;  shot "options-model-unticked" "[ ] model"
$K Space;  shot "options-set-picker" "opus[1m]"
$K Escape; shot "options-set-cancelled" "[ ] model"
$K Escape; shot "options-cancelled" "unchanged"
"$HERE/stop.sh"

# ============================ c: the create flow, through the table
"$HERE/start.sh" 58 >/dev/null
$K s
$K c;      shot "create-type"     "schedule what?"
$K Enter;  shot "create-template" "from which template?"
$K Enter;  shot "create-options"  "skip  continue with nothing ticked"
$K Down; $K Down; $K Down; $K Down; $K Down
shot "create-options-actions"     "check all"
$K Enter;  shot "create-options-checked" "need a value"
$K Down
$K Enter;  shot "create-options-unchecked" "[ ] questions go to a file"
$K Escape; shot "create-cancelled" "cancelled — nothing written"
# d: the delete confirm, refused.
$K d;      shot "sched-delete-confirm" "Delete a-pending.md?"
$K n;      shot "sched-delete-cancelled" "cancelled"
# enter/e: the editor hand-off (EDITOR is /usr/bin/true, so it returns at once)
$K Enter;  shot "sched-after-edit" "scheduled windows"
"$HERE/stop.sh"

python3 "$HERE/normalise.py" "${CAPS:?}"/*.txt
echo "captures: $(ls -1 "${CAPS:?}" | wc -l), lost: $fails"
exit $((fails > 0))
