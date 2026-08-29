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
    game)    warn "Game Mode - Steam IS the session here and will not be stopped" ;;
    *)       warn "session mode unknown - Steam will not be stopped" ;;
  esac
}

cmd_stop() {
  local before; before=$(avail_gb)
  MODE="$(session_mode)"
  if [ "$MODE" != desktop ]; then
    warn "not in Desktop Mode ($MODE) - leaving Steam alone; it may be the session"
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
  step "Starting the Plasma shell"
  if running "$SHELL_UNIT"; then skip "already running"
  else systemctl --user start "$SHELL_UNIT" 2>/dev/null && ok "plasmashell started" \
       || warn "could not start $SHELL_UNIT (try: kstart plasmashell)"; fi

  step "Starting Steam"
  if running "$STEAM_UNIT"; then skip "already running"
  else systemctl --user start "$STEAM_UNIT" 2>/dev/null && ok "Steam started" \
       || warn "could not start $STEAM_UNIT (launch it from the menu)"; fi

  step "Starting the Discover notifier"
  if running "$NOTIFIER_UNIT"; then skip "already running"
  else systemctl --user start "$NOTIFIER_UNIT" 2>/dev/null && ok "notifier started" \
       || warn "could not start $NOTIFIER_UNIT"; fi
  # The Discover GUI itself is transient and deliberately not relaunched.

  sleep 2
  step "Result"
  printf '    available: %s GiB -> %s GiB\n' "$before" "$(avail_gb)"
}

case "${1:-status}" in
  status) cmd_status ;;
  stop)   cmd_stop ;;
  start)  cmd_start ;;
  -h|--help) sed -n '2,15p' "$0" ;;
  *) echo "usage: $(basename "$0") {status|stop|start}" >&2; exit 2 ;;
esac
