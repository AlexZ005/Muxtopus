#!/usr/bin/env bash
# after-update.sh -- put back the handful of things a SteamOS update reverts.
#
#   bash ~/.code/scripts/after-update.sh
#
# WHY ANY OF THIS IS NEEDED
#   / is an A/B partition that updates replace WHOLESALE, and /etc is an
#   overlay whose upper layer lives on the (also A/B) var partition:
#       lowerdir=/new_root/etc
#       upperdir=/new_root/var/lib/overlays/etc/upper
#   So anything written under /etc can revert on a major update: the deck
#   password (/etc/shadow), sshd's config and its enable symlink, and the
#   /etc/hosts entry the e2e suites need.
#
# WHAT NEVER NEEDS REDOING
#   /home is a separate partition and is untouched, so all of this survives:
#   node + npm (~/.local/node), claude / cc / gh (~/.local/bin), ~/.bashrc,
#   ~/.claude (settings AND credentials), ~/.code (repos + these scripts),
#   ~/.ssh/authorized_keys, and the Playwright browsers in ~/.cache.
#
#   Anything installed with pacman is also gone -- which is exactly why
#   setup-deck.sh installs everything under $HOME instead.
set -uo pipefail

if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  echo "==> Inside a Flatpak sandbox; re-executing on the host"
  exec flatpak-spawn --host bash "$0" "$@"
fi

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }

NEEDS_SETUP=0

step "1/4  Home-side tooling (should all have survived)"
for pair in "node:$HOME/.local/node/bin/node" "claude:$HOME/.local/bin/claude" \
            "cc:$HOME/.local/bin/cc" "gh:$HOME/.local/bin/gh"; do
  n="${pair%%:*}"; f="${pair#*:}"
  [ -x "$f" ] && ok "$n present" || warn "$n MISSING - re-run setup-deck.sh"
done
[ -f "$HOME/.claude/.credentials.json" ] && ok "Claude credentials intact" \
  || warn "Claude credentials gone - run: claude  (it will ask you to log in)"
ls "$HOME/.cache/ms-playwright" 2>/dev/null | grep -q chromium- \
  && ok "Playwright browsers intact" || warn "Playwright browsers missing - see setup-deck.sh step 9"

step "2/4  /etc/hosts mapping for e2e"
if [ -x "$HOME/.code/scripts/apply-hosts.sh" ]; then
  "$HOME/.code/scripts/apply-hosts.sh" || NEEDS_SETUP=1
else
  warn "~/.code/scripts/apply-hosts.sh missing"; NEEDS_SETUP=1
fi

step "3/4  Account password (sudo + SSH)"
PWSTATE="$(passwd -S "$USER" 2>/dev/null | awk '{print $2}')"
if [ "$PWSTATE" = "P" ]; then
  ok "password still set for $USER"
else
  warn "password was RESET by the update - set it with: passwd"
  warn "without it neither sudo nor SSH password login works"
  NEEDS_SETUP=1
fi

step "4/4  sshd"
if systemctl is-active --quiet sshd 2>/dev/null; then
  ok "sshd running"
  systemctl is-enabled --quiet sshd 2>/dev/null \
    && ok "sshd enabled at boot" \
    || warn "sshd NOT enabled at boot - run: sudo systemctl enable sshd"
else
  warn "sshd is down - run: sudo systemctl enable --now sshd"
  NEEDS_SETUP=1
fi

echo
if [ "$NEEDS_SETUP" = 1 ]; then
  printf '\033[1m==> Some /etc state needs restoring.\033[0m\n'
  echo "    The full path, which is idempotent and skips what is already fine:"
  echo
  echo "        bash ~/.code/scripts/setup-deck.sh --no-clone"
else
  printf '\033[1m==> Nothing further to do.\033[0m\n'
fi
