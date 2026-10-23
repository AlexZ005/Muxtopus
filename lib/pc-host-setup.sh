#!/usr/bin/env bash
# pc-host-setup.sh -- the Linux half of a pc host: one machine (a WSL2 distro,
# or any Linux box) that takes whole e2e runs (pc slots) and, later, lanes.
#
#   sudo bash pc-host-setup.sh root <user> <ssh-port> "<public key>" [<loopback name>...]
#   bash pc-host-setup.sh user [<node version>] [<playwright version>...]
#
# pc-host-setup.ps1 runs both inside a new WSL distro; on a plain Linux box run
# them yourself. Both are idempotent.
#
# root: the account (uid 1000; an existing uid-1000 account is RENAMED to
# <user>, which is what a fresh Ubuntu WSL image has), sudo for it without a
# password (Playwright's `install-deps` is apt), the packages, and sshd on
# <ssh-port>: key only, that one user, no root. Each <loopback name> is mapped
# to 127.0.0.1 and ::1 in /etc/hosts -- a lane whose APP_URL is
# https://app.example:5173/ needs app.example to be THIS machine here too.
# On WSL it also writes /etc/wsl.conf: systemd on (sshd is a service), <user>
# the default, /etc/hosts not regenerated, and no Windows drives or Windows
# programs (automount and interop off): what runs here needs neither, and a
# lane that cannot see C: cannot damage it.
#
# THE USER MUST BE THE TEST MACHINE'S USER, with the same HOME: a pc run keeps
# every path as it is (lib/e2e-pc.sh), so /home/<user> must be the same folder
# name on both machines.
#
# user: node (the version the lanes use; a tarball from nodejs.org into
# ~/.local/opt, linked from ~/.local/bin -- no system node), and Chromium for
# each Playwright version the lanes use, in ~/.cache/ms-playwright (the
# default PLAYWRIGHT_BROWSERS_PATH, inside the distro).
set -euo pipefail
phase="${1:-}"; shift || true

if [ "$phase" = root ]; then
  user="$1" port="$2" key="$3"; shift 3
  export DEBIAN_FRONTEND=noninteractive
  if grep -qi microsoft /proc/version 2>/dev/null; then
    cat > /etc/wsl.conf <<EOF
# written by muxtopus pc-host-setup.sh
[boot]
systemd=true
[user]
default=$user
[network]
generateHosts=false
hostname=$(hostname)
[automount]
enabled=false
mountFsTab=false
[interop]
enabled=false
appendWindowsPath=false
EOF
  fi
  {
    echo "127.0.0.1 localhost"
    echo "127.0.1.1 $(hostname)"
    echo "::1 localhost ip6-localhost ip6-loopback"
    for n in "$@"; do echo "127.0.0.1 $n"; echo "::1 $n"; done
  } > /etc/hosts
  if ! id "$user" >/dev/null 2>&1; then
    old="$(getent passwd 1000 | cut -d: -f1 || true)"
    if [ -n "$old" ]; then
      usermod -l "$user" -d "/home/$user" -m "$old"
      groupmod -n "$user" "$(id -gn "$user")" || true
    else
      useradd -m -u 1000 -s /bin/bash "$user"
    fi
  fi
  usermod -aG sudo "$user"
  echo "$user ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-muxtopus-$user"; chmod 440 "/etc/sudoers.d/90-muxtopus-$user"
  apt-get update -qq
  apt-get install -y -qq openssh-server rsync git curl ca-certificates build-essential tmux jq python3 python3-venv unzip xz-utils >/dev/null
  install -d -m 700 -o "$user" -g "$user" "/home/$user/.ssh"
  ak="/home/$user/.ssh/authorized_keys"
  touch "$ak"; grep -qxF "$key" "$ak" || echo "$key" >> "$ak"
  chown "$user:$user" "$ak"; chmod 600 "$ak"
  cat > /etc/ssh/sshd_config.d/50-muxtopus.conf <<EOF
# written by muxtopus pc-host-setup.sh: key only, one user
Port $port
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers $user
EOF
  # Ubuntu 24.04 starts sshd from a socket unit by default; the plain service
  # reads Port from the file above, which is the one place it is written.
  if command -v systemctl >/dev/null && [ "$(ps -p 1 -o comm=)" = systemd ]; then
    systemctl disable --now ssh.socket >/dev/null 2>&1 || true
    systemctl enable --now ssh.service >/dev/null 2>&1 || systemctl restart ssh.service
  fi
  echo "pc-host-setup: root done (user $user, sshd :$port, $# loopback names)"
  exit 0
fi

if [ "$phase" = user ]; then
  v="${1:-24.19.0}"; shift || true
  mkdir -p ~/.local/opt ~/.local/bin
  [ -x ~/.local/opt/node-v"$v"-linux-x64/bin/node ] || curl -fsSL "https://nodejs.org/dist/v$v/node-v$v-linux-x64.tar.xz" | tar -xJ -C ~/.local/opt
  for b in node npm npx corepack; do ln -sf ~/.local/opt/node-v"$v"-linux-x64/bin/$b ~/.local/bin/$b; done
  # Non-interactive ssh commands read .bashrc, and Ubuntu's returns early for
  # them: the PATH line goes above that check.
  grep -q 'muxtopus pc-host PATH' ~/.bashrc 2>/dev/null || sed -i '1i export PATH="$HOME/.local/bin:$PATH"  # muxtopus pc-host PATH (before the interactive check)' ~/.bashrc
  export PATH="$HOME/.local/bin:$PATH"
  for pv in "$@"; do
    d=~/.cache/muxtopus-pc/pw-"$pv"; mkdir -p "$d"
    [ -f "$d/package.json" ] || echo '{"private":true}' > "$d/package.json"
    [ -d "$d/node_modules/playwright" ] || (cd "$d" && npm install --no-audit --no-fund "playwright@$pv" >/dev/null 2>&1)
    sudo env PATH="$PATH" node "$d/node_modules/playwright/cli.js" install-deps chromium >/dev/null 2>&1
    node "$d/node_modules/playwright/cli.js" install chromium >/dev/null 2>&1
    echo "pc-host-setup: playwright $pv: $(ls ~/.cache/ms-playwright | tr '\n' ' ')"
  done
  echo "pc-host-setup: user done (node $(node -v))"
  exit 0
fi

sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2
exit 2
