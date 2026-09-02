#!/usr/bin/env bash
# apply-logind.sh -- keep tmux sessions alive after the last SSH client leaves.
#
# THE FAILURE THIS PREVENTS: SteamOS ships
# /etc/systemd/logind.conf.d/killuserprocesses.conf with KillUserProcesses=True,
# so logind kills every process of a login session the moment that session ends.
# The tmux SERVER is started from your SSH session and stays in that session's
# scope (only its panes get their own tmux-spawn-*.scope), so it is killed too --
# taking every window with it. Measured: an SSH link dropped by powering off the
# client machine, sshd noticed 20 minutes later, and in that same second the
# three pane scopes were finalized ("Consumed 2min 35s CPU, 495.4M memory peak").
# Two Claude Code sessions died with them. Detaching first does not help: the
# kill is triggered by the last SESSION closing, not by the attach state.
#
# Two settings are needed and they fix different halves:
#   KillUserProcesses=no   the tmux server survives its own session ending
#   enable-linger          the user manager (and the pane scopes under it)
#                          keeps running with nobody logged in
#
# WHY THIS NEEDS RE-RUNNING: /etc is an overlay whose upper layer lives on the
# A/B `var` partition, and /var/lib/systemd/linger is on that partition too, so
# a major SteamOS update can revert both. after-update.sh calls this;
# setup-deck.sh calls it too.
#
# Requires sudo and will prompt for the deck password.
set -uo pipefail

if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  exec flatpak-spawn --host bash "$0" "$@"
fi

DROPIN="/etc/systemd/logind.conf.d/zz-keep-tmux.conf"
# 'zz-' so it sorts AFTER SteamOS's own killuserprocesses.conf: drop-ins are
# read in filename order and the last assignment wins. Overriding rather than
# editing the vendor file means a SteamOS update reinstalling it changes nothing.
read -r -d '' WANT <<'CONF'
# theprototype (added by apply-logind.sh) -- overrides SteamOS's
# killuserprocesses.conf so a detached tmux server survives logout.
[Login]
KillUserProcesses=no
CONF

ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }

RC=0

# --- 1. The drop-in ----------------------------------------------------------
if [ "$(cat "$DROPIN" 2>/dev/null)" = "$WANT" ]; then
  skip "$DROPIN already in place"
elif ! command -v sudo >/dev/null 2>&1; then
  warn "sudo not available - write $DROPIN by hand:"; printf '%s\n' "$WANT"; RC=1
else
  echo "==> $DROPIN needs writing (sudo will prompt)"
  # /etc is an overlay and takes writes even while steamos-readonly reports
  # 'enabled', so unlocking the rootfs is only a fallback for when it does not.
  if printf '%s\n' "$WANT" | sudo tee "$DROPIN" >/dev/null 2>&1; then
    ok "drop-in written"
  elif command -v steamos-readonly >/dev/null 2>&1 \
       && sudo steamos-readonly disable 2>/dev/null; then
    printf '%s\n' "$WANT" | sudo tee "$DROPIN" >/dev/null && ok "drop-in written (rootfs unlocked)" || { warn "could not write $DROPIN"; RC=1; }
    sudo steamos-readonly enable && ok "rootfs re-locked" \
      || warn "rootfs LEFT WRITABLE - run: sudo steamos-readonly enable"
  else
    warn "could not write $DROPIN"; RC=1
  fi
fi

# --- 2. Lingering ------------------------------------------------------------
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = "yes" ]; then
  skip "lingering already enabled for $USER"
elif sudo loginctl enable-linger "$USER"; then
  ok "lingering enabled for $USER"
else
  warn "could not enable lingering - run: sudo loginctl enable-linger $USER"; RC=1
fi

# --- 3. Make it LIVE, and prove it -------------------------------------------
# Writing the file is not the fix. logind reads its config once at start, so
# until it is told otherwise the old value is still what kills your session --
# which is exactly how this was found: the drop-in was on disk, linger was on,
# and a test tmux session was still dead 20 seconds after the client left.
# Reload, never restart: restarting logind on a Deck with a live graphical
# session on seat0 can take that session down with it.
live() { busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
           org.freedesktop.login1.Manager KillUserProcesses 2>/dev/null; }

if [ "$(live)" = "b false" ]; then
  ok "verified: logind is running with KillUserProcesses=no"
else
  echo "==> logind is still running the old config; reloading"
  if sudo systemctl reload systemd-logind 2>/dev/null && [ "$(live)" = "b false" ]; then
    ok "verified: logind reloaded, KillUserProcesses=no"
  else
    warn "STILL LIVE: logind reports KillUserProcesses=$(live)"
    warn "the drop-in is on disk but takes effect at the next reboot -- until"
    warn "then a disconnect still kills tmux. Reboot when convenient."
    RC=1
  fi
fi

exit "$RC"
