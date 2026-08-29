#!/usr/bin/env bash
# apply-hosts.sh -- map theprototype.app -> 127.0.0.1 so the e2e suites can run
# against https://theprototype.app:5173 (they are hosts-mapped by design).
#
# WHY THIS NEEDS RE-RUNNING: SteamOS keeps / on a read-only A/B partition that
# is REPLACED wholesale by every system update, so /etc/hosts reverts to stock.
# after-update.sh calls this; setup-deck.sh calls it too.
#
# Requires sudo and will prompt for the deck password.
#
# NOTE: only the bare apex is mapped. peerjs.theprototype.app must keep
# resolving to the real signaling box, or two-peer tests cannot meet.
set -uo pipefail

MARKER="# theprototype e2e (added by apply-hosts.sh)"
ENTRY="127.0.0.1      theprototype.app"

ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }

if grep -qE '^[^#]*[[:space:]]theprototype\.app([[:space:]]|$)' /etc/hosts 2>/dev/null; then
  skip "theprototype.app already mapped in /etc/hosts"
  exit 0
fi

if ! command -v sudo >/dev/null 2>&1; then
  warn "sudo not available - add this line to /etc/hosts by hand:"; echo "      $ENTRY"; exit 1
fi

echo "==> /etc/hosts needs theprototype.app -> 127.0.0.1 (sudo will prompt)"

RO_WAS_ENABLED=0
if command -v steamos-readonly >/dev/null 2>&1; then
  if [ "$(steamos-readonly status 2>/dev/null | tr -d '[:space:]')" = "enabled" ]; then
    RO_WAS_ENABLED=1
    sudo steamos-readonly disable || { warn "could not unlock the rootfs"; exit 1; }
    ok "rootfs unlocked"
  fi
fi

if printf '%s\n%s\n' "$MARKER" "$ENTRY" | sudo tee -a /etc/hosts >/dev/null; then
  ok "mapping added"
else
  warn "could not write /etc/hosts"
fi

# Always try to re-lock, even if the write failed -- leaving / writable on
# SteamOS invites a half-written rootfs on the next update.
if [ "$RO_WAS_ENABLED" = 1 ]; then
  sudo steamos-readonly enable && ok "rootfs re-locked" || warn "rootfs LEFT WRITABLE - run: sudo steamos-readonly enable"
fi

if getent hosts theprototype.app | grep -q '127.0.0.1'; then
  ok "verified: theprototype.app -> 127.0.0.1"
else
  warn "not resolving yet - check /etc/hosts"
fi
