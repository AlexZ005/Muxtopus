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
#   password (/etc/shadow), sshd's config and its enable symlink, the
#   /etc/hosts entry the e2e suites need, the sudoers.d rule for passwordless
#   sudo, and the logind drop-in that stops tmux being killed on disconnect
#   (whose linger marker sits on the var partition too).
#
# WHAT NEVER NEEDS REDOING
#   /home is a separate partition and is untouched, so all of this survives:
#   node + npm (~/.local/node), claude / muxtopus / gh (~/.local/bin), ~/.bashrc,
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

step "1/8  Home-side tooling (should all have survived)"
for pair in "node:$HOME/.local/node/bin/node" "claude:$HOME/.local/bin/claude" \
            "muxtopus:$HOME/.local/bin/muxtopus" \
            "gh:$HOME/.local/bin/gh" \
            "terraform:$HOME/.local/bin/terraform" "aws:$HOME/.local/bin/aws"; do
  n="${pair%%:*}"; f="${pair#*:}"
  [ -x "$f" ] && ok "$n present" || warn "$n MISSING - re-run setup-deck.sh"
done
for cfg in "$HOME"/.claude "$HOME"/.claude-*; do
  [ -d "$cfg" ] || continue
  case "$cfg" in *.bak|*.old|*~) continue ;; esac
  acct="${cfg##*/}"; acct="${acct#.claude}"; acct="${acct#-}"; acct="${acct:-personal}"
  if [ -f "$cfg/.credentials.json" ]; then
    ok "Claude credentials intact ($acct)"
  else
    # The DEFAULT account is logged in by a bare `claude`. Naming its config
    # dir would send it to the theme picker instead of the login menu, because
    # its onboarding state lives in ~/.claude.json, not inside ~/.claude.
    if [ "$acct" = personal ]; then
      warn "Claude credentials gone ($acct) - run: claude  (it will ask you to log in)"
    else
      warn "Claude credentials gone ($acct) - run: CLAUDE_CONFIG_DIR=$cfg claude  (it will ask you to log in)"
    fi
  fi
done
ls "$HOME/.cache/ms-playwright" 2>/dev/null | grep -q chromium- \
  && ok "Playwright browsers intact" || warn "Playwright browsers missing - see setup-deck.sh step 10"

step "2/8  Dashboard runtime"
# A venv is pinned to the python it was built from, so a SteamOS update that
# moves python3 breaks it. deck-status.sh falls back to bash either way, but
# rebuild it here so the good renderer comes back automatically.
VENV="$HOME/.code/scripts/.venv"
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import rich' 2>/dev/null; then
  ok "rich venv intact"
elif command -v python3 >/dev/null 2>&1; then
  rm -rf "$VENV"
  if python3 -m venv "$VENV" >/dev/null 2>&1 && "$VENV/bin/pip" install --quiet rich >/dev/null 2>&1; then
    ok "rich venv rebuilt"
  else
    warn "venv rebuild failed - deck-status.sh will use its bash renderer"
  fi
else
  warn "python3 missing - deck-status.sh will use its bash renderer"
fi

step "3/8  Passwordless sudo"
# First, because the two steps after it write /etc: with the rule in place they
# run unattended even over a bare 'ssh deck bash ~/.code/scripts/after-update.sh'.
if [ -x "$HOME/.code/scripts/apply-sudo.sh" ]; then
  "$HOME/.code/scripts/apply-sudo.sh" || NEEDS_SETUP=1
else
  warn "~/.code/scripts/apply-sudo.sh missing"; NEEDS_SETUP=1
fi

step "4/8  /etc/hosts mapping for e2e"
if [ -x "$HOME/.code/scripts/apply-hosts.sh" ]; then
  "$HOME/.code/scripts/apply-hosts.sh" || NEEDS_SETUP=1
else
  warn "~/.code/scripts/apply-hosts.sh missing"; NEEDS_SETUP=1
fi

step "5/8  tmux session persistence"
# The drop-in lives on the /etc overlay and the linger marker on /var, so an
# update can revert either and silently take detached tmux sessions with it.
if [ -x "$HOME/.code/scripts/apply-logind.sh" ]; then
  "$HOME/.code/scripts/apply-logind.sh" || NEEDS_SETUP=1
else
  warn "~/.code/scripts/apply-logind.sh missing"; NEEDS_SETUP=1
fi

step "6/8  Account password (sudo + SSH)"
PWSTATE="$(passwd -S "$USER" 2>/dev/null | awk '{print $2}')"
if [ "$PWSTATE" = "P" ]; then
  ok "password still set for $USER"
else
  warn "password was RESET by the update - set it with: passwd"
  warn "without it neither sudo nor SSH password login works"
  NEEDS_SETUP=1
fi

step "7/8  sshd"
if systemctl is-active --quiet sshd 2>/dev/null; then
  ok "sshd running"
  systemctl is-enabled --quiet sshd 2>/dev/null \
    && ok "sshd enabled at boot" \
    || warn "sshd NOT enabled at boot - run: sudo systemctl enable sshd"
else
  warn "sshd is down - run: sudo systemctl enable --now sshd"
  NEEDS_SETUP=1
fi

step "8/8  Usage-limit watchdog"
# The unit lives in ~/.config (home, so it survives), but its ENABLE symlink is
# written by systemctl into the same tree -- what an update can take away is the
# lingering it needs, which step 5 restores. Re-running --install is idempotent.
if [ ! -x "$HOME/.code/scripts/claude-watchdog.sh" ]; then
  warn "~/.code/scripts/claude-watchdog.sh missing"; NEEDS_SETUP=1
elif systemctl --user is-active --quiet claude-watchdog.service 2>/dev/null; then
  ok "watchdog running"
  [ -f "${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog/enabled" ] \
    && ok "watchdog armed" \
    || warn "watchdog is DISARMED - it reports but will not prompt (w on the dashboard)"
else
  warn "watchdog not running - reinstalling"
  "$HOME/.code/scripts/claude-watchdog.sh" --install | sed 's/^/    /' || NEEDS_SETUP=1
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
