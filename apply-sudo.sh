#!/usr/bin/env bash
# apply-sudo.sh -- passwordless sudo for this account.
#
# WHY: every other apply-* helper here writes /etc state and so prompts for a
# password. That makes them unrunnable from anything without a terminal -- a
# remote 'ssh deck ...' without -t, a tmux pane restoring itself, an agent
# repairing the box after an update -- which is precisely when you want them to
# work. With this in place, setup-deck.sh and after-update.sh run unattended.
#
# THE TRADE, stated plainly: anyone who can open a shell as this user becomes
# root with no further check. That is acceptable here because the account is
# already the sole owner of the machine and SSH is key-only on a home LAN; it
# would not be on a shared or exposed host.
#
# WHY THIS NEEDS RE-RUNNING: /etc/sudoers.d lives on the /etc overlay, whose
# upper layer is on the A/B var partition, so a major SteamOS update can revert
# it. after-update.sh calls this; setup-deck.sh calls it too.
#
# The first run prompts for the deck password. Every run after that does not.
set -uo pipefail

if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  exec flatpak-spawn --host bash "$0" "$@"
fi

RULE="/etc/sudoers.d/99-$USER-nopasswd"
# Staged under a name containing a dot: sudo's includedir SKIPS such files, so
# a half-written or invalid staging file can never be read as policy.
STAGE="$RULE.staging"
WANT="$USER ALL=(ALL:ALL) NOPASSWD: ALL"

ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }

if sudo -n true 2>/dev/null; then
  skip "passwordless sudo already working for $USER"
  exit 0
fi

if ! command -v sudo >/dev/null 2>&1; then
  warn "sudo not available on this machine"; exit 1
fi

echo "==> granting passwordless sudo to $USER (sudo will prompt once more)"

# Validate BEFORE the file can be read as policy. A syntactically broken
# sudoers file is not a cosmetic problem: sudo refuses to run at all, and the
# way back is a root shell you may not have. visudo -c is the whole safety net.
if ! printf '%s\n' "$WANT" | sudo tee "$STAGE" >/dev/null; then
  warn "could not write $STAGE"; exit 1
fi
sudo chmod 0440 "$STAGE"

if ! sudo visudo -cf "$STAGE" >/dev/null 2>&1; then
  warn "REFUSING: visudo rejected the rule, leaving sudo untouched"
  sudo rm -f "$STAGE"
  exit 1
fi
ok "rule validated by visudo"

if sudo install -m 0440 -o root -g root "$STAGE" "$RULE"; then
  ok "installed $RULE"
else
  warn "could not install $RULE"; sudo rm -f "$STAGE"; exit 1
fi
sudo rm -f "$STAGE"

# Prove it, rather than assume it: a distribution that does not include
# /etc/sudoers.d from its main sudoers file would take the write and change
# nothing. sudo caches a recent authentication for a few minutes, so drop that
# first or this reads as a pass either way.
sudo -k
if sudo -n true 2>/dev/null; then
  ok "verified: sudo now runs without a password"
else
  warn "rule installed but sudo still asks -- check that /etc/sudoers has:"
  warn "   @includedir /etc/sudoers.d"
  exit 1
fi
