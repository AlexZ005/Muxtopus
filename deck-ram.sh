#!/usr/bin/env bash
# deck-ram.sh -- free RAM for parallel dev lanes by stopping the desktop
# extras, then put them back. Run manually; nothing here is automatic.
#
#   deck-ram.sh status    what is running, and how much RAM is free
#   deck-ram.sh stop      stop Steam, Discover and the Plasma shell
#   deck-ram.sh start     bring them back
#
# SAFETY: this NEVER touches kwin_wayland. That is the Wayland compositor --
# killing it takes down the entire graphical session and every open window.
# Stopping plasmashell removes only the panel and desktop icons; your windows,
# terminals and tmux sessions keep running untouched.
#
# Safe to run over SSH: XDG_RUNTIME_DIR is set so systemctl --user reaches the
# same user manager that owns the desktop session.
set -uo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

SHELL_UNIT="plasma-plasmashell.service"
STEAM_UNIT="app-steam@autostart.service"
GAME_STEAM_UNIT="steam-launcher.service"   # Steam in Game Mode (NOT the compositor)
NOTIFIER_UNIT="app-org.kde.discover.notifier@autostart.service"

ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

avail_gb() { awk '/^MemAvailable:/ {printf "%.1f", $2/1048576}' /proc/meminfo; }
running()  { systemctl --user is-active --quiet "$1" 2>/dev/null; }

# Discover's GUI unit carries a random per-launch hash, so match it at runtime.
discover_units() {
  systemctl --user list-units --plain --no-legend --no-pager \
    'app-org.kde.discover@*.service' 2>/dev/null | awk '{print $1}'

# Steam may run as the autostart unit or a transient one; match both.
steam_units() { systemctl --user list-units --plain --no-legend --no-pager 'app-steam@*.service' 2>/dev/null | awk '{print $1}'; }
}

rss_mb() { # total RSS of a process pattern, in MB
  local total
  total=$(ps -eo rss,args --no-headers 2>/dev/null | grep -F -- "$1" | grep -v grep \
          | awk '{s+=$1} END {print s+0}')
  echo $((total / 1024))
}

# Which session is this? In GAME MODE Steam *is* the session (sddm autologin
# -> start-gamescope-session), so stopping it drops you to a black screen.
# In DESKTOP MODE Steam is just an app under app-steam@*.service.
session_mode() {
  if pgrep -x kwin_wayland >/dev/null 2>&1; then echo desktop
  elif systemctl --user is-active --quiet gamescope-session.target 2>/dev/null || pgrep -f start-gamescope-session >/dev/null 2>&1; then echo game
  else echo unknown; fi
}

cmd_status() {
  step "Memory"
  free -h | sed -n '1,2p' | sed 's/^/    /'
  printf '    available: \033[1m%s GiB\033[0m\n' "$(avail_gb)"
  step "Desktop extras"
  for u in "$SHELL_UNIT" "$STEAM_UNIT" "$NOTIFIER_UNIT"; do
    if running "$u"; then ok "$u running"; else skip "$u stopped"; fi
  done
  for u in $(discover_units); do ok "$u running"; done
  step "Approximate RSS"
  printf '    %-14s %5s MB\n' steam        "$(rss_mb 'Steam/ubuntu12_32')"
  printf '    %-14s %5s MB\n' steamwebhelper "$(rss_mb steamwebhelper)"
  printf '    %-14s %5s MB\n' plasmashell  "$(rss_mb /usr/bin/plasmashell)"
  printf '    %-14s %5s MB\n' discover     "$(rss_mb plasma-discover)"
  step "Session"
  case "$(session_mode)" in
    desktop) ok "Desktop Mode (kwin_wayland alive; Steam is stoppable)" ;;
    game)    ok   "Game Mode - stopping Steam leaves an on-screen button to restore it" ;;
    *)       warn "session mode unknown - Steam will not be stopped" ;;
  esac
}


# In GAME MODE Steam is the only visible client, so stopping it leaves a black
# screen. But gamescope-session.service (the compositor) is a SEPARATE unit and
# steam-launcher.service is only PartOf=graphical-session.target, so stopping
# Steam alone leaves gamescope running -- there is still something to draw on.
#
# The dialog runs DETACHED so `deck-ram.sh stop` returns immediately, and Steam
# is restarted when it exits FOR ANY REASON, including failing to appear. That
# is the rollback: a broken dialog restores Steam rather than stranding you.
# STOPPING STEAM IN GAME MODE DOES NOT WORK, and must not be attempted.
#
# MEASURED: `systemctl --user stop steam-launcher.service` never even takes
# effect -- the unit reads `active` again within 2 seconds, with no script
# involved, because in Game Mode Steam IS the session and the session manager
# relaunches it. That relaunch is the same mechanism that recovers a crashed
# Game Mode, so defeating it would mean masking a unit: a persistent system
# change, and the one thing this machine is explicitly not to have.
#
# It would buy almost nothing anyway. Game Mode loads no KDE, so it already
# sits near 19 GiB available, and stopping Steam frees ~0.2 GiB. Desktop Mode
# is where the ~3.8 GiB actually is, and that path works.
#
# (An on-screen zenity dialog with a restart button was built and tested here.
# The dialog itself works -- gamescope keeps running and zenity draws on
# WAYLAND_DISPLAY=gamescope-0 -- but it is pointless when the thing it offers
# to undo undoes itself in two seconds.)
game_stop() {
  warn "Game Mode: Steam is the session and is relaunched automatically"
  warn "measured: the unit reads active again ~2s after a stop"
  warn "suppressing that needs a masked unit - a persistent system change"
  skip "little to reclaim here anyway ($(avail_gb) GiB already available)"
  printf '
    For real savings switch to Desktop Mode and run this there.
'
  printf '    Otherwise just work over SSH: Game Mode is already the leaner session.
'
  return 0
}

cmd_stop() {
  local before; before=$(avail_gb)
  MODE="$(session_mode)"
  if [ "$MODE" = game ]; then
    game_stop; return 0
  elif [ "$MODE" != desktop ]; then
    warn "session mode unknown - leaving Steam alone; it may be the session"
  fi
  step "Stopping Steam"
  if [ "$MODE" != desktop ]; then
    skip "skipped outside Desktop Mode"
  else
  # NEVER invoke the 'steam' wrapper here. /usr/bin/steam is a launcher whose
  # last line is: exec /usr/lib/steam/steam -steamdeck -pipewire "$@"
  # so 'steam -shutdown' starts a NEW process OUTSIDE this unit's cgroup.
  # Stopping the unit then kills the cgroup and that launcher immediately
  # brings Steam back -- the "Steam restarts when I run this" symptom.
  # The unit is KillMode=control-group, so stopping it takes the whole tree.
  su="$(steam_units)"
  if [ -n "$su" ]; then
    for u in $su; do systemctl --user stop "$u" 2>/dev/null; done
    for _ in $(seq 1 20); do
      [ -z "$(steam_units)" ] && break
      sleep 1
    done
    if [ -z "$(steam_units)" ]; then
      ok "Steam stopped"
    else
      warn "Steam unit still active: $(steam_units)"
    fi
  elif pgrep -f 'Steam/ubuntu12_32/steam' >/dev/null; then
    warn "Steam is running outside a systemd unit - quit it from its own menu"
  else
    skip "Steam not running"
  fi
  fi

  step "Stopping Discover"
  local found=0
  for u in $(discover_units); do systemctl --user stop "$u" 2>/dev/null; found=1; done
  running "$NOTIFIER_UNIT" && { systemctl --user stop "$NOTIFIER_UNIT" 2>/dev/null; found=1; }
  pgrep -x plasma-discover >/dev/null && { pkill -x plasma-discover 2>/dev/null; found=1; }
  [ "$found" = 1 ] && ok "Discover stopped" || skip "Discover not running"

  step "Stopping the Plasma shell"
  if running "$SHELL_UNIT"; then
    systemctl --user stop "$SHELL_UNIT" 2>/dev/null && ok "plasmashell stopped (panel gone, windows fine)" \
      || warn "could not stop $SHELL_UNIT"
  else
    skip "plasmashell not running"
  fi

  sleep 2
  step "Result"
  printf '    available: %s GiB -> \033[1m%s GiB\033[0m\n' "$before" "$(avail_gb)"
  [ "$MODE" = desktop ] && ! pgrep -x kwin_wayland >/dev/null && warn "kwin_wayland is gone - the session may be broken"
  return 0
}

cmd_start() {
  local before; before=$(avail_gb)
  MODE="$(session_mode)"

  step "Starting Steam"
  if [ "$MODE" = game ]; then
    if systemctl --user is-active --quiet "$GAME_STEAM_UNIT"; then skip "already running"
    elif systemctl --user start "$GAME_STEAM_UNIT" 2>/dev/null; then ok "Steam started"
    else warn "could not start $GAME_STEAM_UNIT"; fi
  elif running "$STEAM_UNIT"; then skip "already running"
  elif systemctl --user start "$STEAM_UNIT" 2>/dev/null; then ok "Steam started"
  else warn "could not start $STEAM_UNIT (launch it from the menu)"; fi

  if [ "$MODE" = game ]; then
    skip "Plasma shell and Discover are Desktop Mode only"
  else
    step "Starting the Plasma shell"
    if running "$SHELL_UNIT"; then skip "already running"
    elif systemctl --user start "$SHELL_UNIT" 2>/dev/null; then ok "plasmashell started"
    else warn "could not start $SHELL_UNIT (try: kstart plasmashell)"; fi

    step "Starting the Discover notifier"
    if running "$NOTIFIER_UNIT"; then skip "already running"
    elif systemctl --user start "$NOTIFIER_UNIT" 2>/dev/null; then ok "notifier started"
    else warn "could not start $NOTIFIER_UNIT"; fi
    # The Discover GUI itself is transient and deliberately not relaunched.
  fi

  sleep 2
  step "Result"
  printf '    available: %s GiB -> %s GiB\n' "$before" "$(avail_gb)"
  return 0
}


# ---------------------------------------------------------------------------
# `show` -- put a read-only status panel on the Deck's own screen.
#
# Works in BOTH sessions: zenity draws on whichever compositor is running
# (gamescope-0 in Game Mode, the Plasma display in Desktop Mode). Nothing is
# started or stopped, so this is safe at any time; the button just closes the
# panel and hands the screen back.
# ---------------------------------------------------------------------------

# Total RSS of the process group owning a listening port, in MB. npm and vite
# are separate processes, so summing the GROUP is what gives the real figure.
port_mb() {
  local pid pgid
  pid=$(ss -lptnH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)
  [ -z "$pid" ] && return 1
  pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -z "$pgid" ] && return 1
  ps -eo pgid,rss --no-headers | awk -v g="$pgid" '$1==g {s+=$2} END {printf "%d", s/1024}'
}

build_report() {
  local total avail cap st tmp mb found=0
  total=$(awk '/^MemTotal:/     {printf "%.1f", $2/1048576}' /proc/meminfo)
  avail=$(awk '/^MemAvailable:/ {printf "%.1f", $2/1048576}' /proc/meminfo)

  echo "MEMORY"
  echo "  available    $avail GiB of $total GiB"
  echo "  session      $(session_mode)"
  echo
  echo "DEV SERVERS"
  for prt in 5173 5174 5175 5176 5177 5178 5179 5180; do
    if mb=$(port_mb "$prt"); then
      echo "  :$prt        $mb MB"
      found=1
    fi
  done
  [ "$found" = 0 ] && echo "  (none listening on 5173-5180)"
  echo
  echo "TOP MEMORY"
  ps -eo rss,comm --no-headers --sort=-rss | head -6 | while read -r r c; do
    echo "  $(printf '%-16s' "$c") $((r / 1024)) MB"
  done
  echo
  echo "CLAUDE"
  echo "  sessions     $(pgrep -cx claude 2>/dev/null | head -1)"
  echo
  echo "DISK"
  echo "  /home        $(df -h /home --output=avail 2>/dev/null | tail -1 | tr -d ' ') free"
  echo
  echo "SYSTEM"
  cap=$(cat /sys/class/power_supply/BAT*/capacity 2>/dev/null | head -1)
  st=$(cat /sys/class/power_supply/BAT*/status 2>/dev/null | head -1)
  tmp=$(for z in /sys/class/thermal/thermal_zone*/temp; do cat "$z" 2>/dev/null; done | sort -rn | head -1 | awk '{printf "%.0f", $1/1000}')
  echo "  battery      ${cap:-?}% ${st:-?}"
  echo "  cpu temp     ${tmp:-?} C"
  echo "  uptime       $(uptime -p 2>/dev/null | sed 's/^up //')"
}

cmd_show() {
  local f=/tmp/deck-ram-report.txt zpid w
  build_report > "$f"
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

  if ! command -v zenity >/dev/null 2>&1; then
    warn "zenity not installed - printing here instead"
    cat "$f"
    return 0
  fi

  # In GAME MODE gamescope composites ONLY the focused app, so an ordinary
  # window is invisible. The way over that is the same one mangoapp uses: be
  # an X11 client on :0 and set GAMESCOPE_EXTERNAL_OVERLAY=1 on the window,
  # which gamescope then draws OVER the game. That atom is an X11 property,
  # so we must force the X11 backend -- leaving WAYLAND_DISPLAY set would put
  # zenity on Wayland where the atom cannot be applied at all.
  if [ "$(session_mode)" = game ]; then
    unset WAYLAND_DISPLAY
    export GDK_BACKEND=x11 DISPLAY="${DISPLAY:-:0}"
  fi

  # SteamOS sets logind KillUserProcesses=True, so anything spawned from an
  # SSH login session is reaped the moment that session ends -- setsid does not
  # help, because logind tracks by cgroup. Over SSH the dialog therefore has to
  # be handed to the USER MANAGER via a transient scope, which outlives us.
  if [ -n "${SSH_CONNECTION:-}" ] && command -v systemd-run >/dev/null 2>&1; then
    systemd-run --user --scope --quiet --collect       zenity --text-info --filename="$f" --title="Deck status" --width=560 --height=620 --ok-label="Back to Game Mode" --timeout=90 >/dev/null 2>&1 &
    zpid=""
  else
    zenity --text-info --filename="$f" --title="Deck status" --width=560 --height=620 --ok-label="Back to Game Mode" --timeout=90 >/dev/null 2>&1 &
    zpid=$!
  fi

  if [ "$(session_mode)" = game ]; then
    for _ in $(seq 1 25); do
      w=$(for c in $(xwininfo -root -children 2>/dev/null | grep -oE '0x[0-9a-f]{5,}'); do
            xprop -id "$c" WM_CLASS 2>/dev/null | grep -qi zenity && echo "$c" && break
          done)
      [ -n "$w" ] && break
      sleep 0.3
    done
    if [ -n "$w" ]; then
      xprop -id "$w" -f GAMESCOPE_EXTERNAL_OVERLAY 32c -set GAMESCOPE_EXTERNAL_OVERLAY 1 2>/dev/null \
        && ok "panel shown as a gamescope overlay ($w)" \
        || warn "could not set the overlay atom - the panel may be hidden behind Steam"
    else
      warn "no zenity window found - the panel may be hidden behind Steam"
    fi
  fi

  if [ -n "$zpid" ]; then
    wait "$zpid" 2>/dev/null
    ok "panel closed"
  else
    ok "panel left running in its own scope (it survives this SSH session)"
  fi
}

case "${1:-status}" in
  status) cmd_status ;;
  show)   cmd_show ;;
  hide)   pkill -x zenity 2>/dev/null && ok "panel closed" || skip "no panel open" ;;
  stop)   cmd_stop ;;
  start)  cmd_start ;;
  -h|--help) sed -n '2,15p' "$0" ;;
  *) echo "usage: $(basename "$0") {status|show|hide|stop|start}" >&2; exit 2 ;;
esac
