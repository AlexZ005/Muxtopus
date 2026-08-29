#!/usr/bin/env bash
# setup-deck.sh -- rebuild this machine's dev environment after a SteamOS
# reset, reimage, or major update. Idempotent: safe to re-run any time;
# anything already in place is reported and skipped.
#
#   bash ~/.code/setup-deck.sh              full run
#   bash ~/.code/setup-deck.sh --no-ssh     skip the passwd + sshd steps
#   bash ~/.code/setup-deck.sh --no-clone   skip cloning the org repos
#
# Everything installs under $HOME, which lives on the `home` partition and is
# NOT touched by SteamOS A/B updates. Nothing is written to / or /usr, which
# are replaced wholesale on every update -- that is why we avoid pacman.
set -uo pipefail

# --- Always run on the host --------------------------------------------------
# Inside VSCode's Flatpak sandbox, passwd/sudo/systemctl/tmux would all target
# the sandbox rather than the real system.
if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  echo "==> Inside a Flatpak sandbox; re-executing on the host"
  exec flatpak-spawn --host bash "$0" "$@"
fi

DO_SSH=1; DO_CLONE=1
for a in "$@"; do
  case "$a" in
    --no-ssh)   DO_SSH=0 ;;
    --no-clone) DO_CLONE=0 ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

BIN="$HOME/.local/bin"
ORG="theprototype-app"
mkdir -p "$BIN"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m+\033[0m %s\n' "$*"; }
skip() { printf '    \033[90m.\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '    \033[31mx %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. Shell environment ----------------------------------------------------
step "1/8  Shell environment (~/.bashrc)"
need_path=1; need_gh=1
grep -q '\.local/bin'   "$HOME/.bashrc" 2>/dev/null && need_path=0
grep -q 'GH_CONFIG_DIR'  "$HOME/.bashrc" 2>/dev/null && need_gh=0
if [ "$need_path" = 0 ] && [ "$need_gh" = 0 ]; then
  skip "already configured"
else
  [ -f "$HOME/.bashrc" ] && cp "$HOME/.bashrc" "$HOME/.bashrc.bak"
  # Prepended, so it runs BEFORE the `[[ $- != *i* ]] && return` guard that
  # Arch's default .bashrc opens with. Without this, a non-interactive
  # `ssh host 'bash -lc cc'` returns before PATH is ever extended.
  {
    echo "# Added by setup-deck: user-local binaries (gh, claude, cc)."
    if [ "$need_path" = 1 ]; then
      printf '%s\n' 'case ":$PATH:" in' \
        '  *":$HOME/.local/bin:"*) ;;' \
        '  *) export PATH="$HOME/.local/bin:$PATH" ;;' \
        'esac'
    fi
    if [ "$need_gh" = 1 ]; then
      printf '%s\n' '# VSCode Flatpak redirects XDG_CONFIG_HOME; pin gh at the real config.' \
        'export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"'
    fi
    echo
    cat "$HOME/.bashrc" 2>/dev/null
  } > "$HOME/.bashrc.new" && mv "$HOME/.bashrc.new" "$HOME/.bashrc"
  [ "$need_path" = 1 ] && ok "PATH prepended"
  [ "$need_gh"   = 1 ] && ok "GH_CONFIG_DIR prepended"
  ok "backup at ~/.bashrc.bak"
fi
export PATH="$BIN:$PATH"
export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"

# --- 2. Preinstalled tools ---------------------------------------------------
step "2/8  Checking preinstalled tools"
for t in git tmux curl jq python3 ssh; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t $(command -v $t)"
  else warn "$t MISSING - unexpected on SteamOS"; fi
done

# --- 3. GitHub CLI -----------------------------------------------------------
step "3/8  GitHub CLI (gh)"
if [ -x "$BIN/gh" ]; then
  skip "gh $("$BIN/gh" --version | head -1 | awk '{print $3}') already at $BIN/gh"
else
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  VER="$(curl -sL https://api.github.com/repos/cli/cli/releases/latest \
        | grep -m1 '"tag_name"' | sed -E 's/.*"v?([^"]+)".*/\1/')"
  [ -n "$VER" ] || die "could not determine latest gh version"
  ok "latest is v$VER, downloading"
  curl -fL --progress-bar -o "$TMP/gh.tgz" \
    "https://github.com/cli/cli/releases/download/v${VER}/gh_${VER}_linux_amd64.tar.gz" \
    || die "download failed"
  curl -fsL -o "$TMP/sums" \
    "https://github.com/cli/cli/releases/download/v${VER}/gh_${VER}_checksums.txt" \
    || die "checksum download failed"
  EXP="$(grep "gh_${VER}_linux_amd64.tar.gz" "$TMP/sums" | awk '{print $1}')"
  ACT="$(sha256sum "$TMP/gh.tgz" | awk '{print $1}')"
  [ "$EXP" = "$ACT" ] || die "CHECKSUM MISMATCH - refusing to install"
  ok "sha256 verified"
  tar xzf "$TMP/gh.tgz" -C "$TMP"
  install -m 755 "$TMP/gh_${VER}_linux_amd64/bin/gh" "$BIN/gh"
  mkdir -p "$HOME/.local/share/man/man1"
  cp -r "$TMP/gh_${VER}_linux_amd64/share/man/man1/." "$HOME/.local/share/man/man1/" 2>/dev/null || true
  ok "gh $("$BIN/gh" --version | head -1 | awk '{print $3}') installed"
  rm -rf "$TMP"; trap - EXIT
fi

# --- 4. Claude Code CLI ------------------------------------------------------
step "4/8  Claude Code CLI"
if [ -x "$BIN/claude" ]; then
  skip "claude $("$BIN/claude" --version 2>/dev/null | awk '{print $1}') already at $BIN/claude"
else
  T="$(mktemp -d)"
  # Downloaded to a file first, rather than piped straight into a shell.
  if curl -fsSL https://claude.ai/install.sh -o "$T/install.sh"; then
    bash "$T/install.sh" >/dev/null 2>&1 \
      && ok "claude $("$BIN/claude" --version 2>/dev/null | awk '{print $1}') installed" \
      || warn "installer failed - see https://code.claude.com/docs"
  else
    warn "could not fetch installer (offline?)"
  fi
  rm -rf "$T"
fi
[ -f "$HOME/.claude/.credentials.json" ] \
  && ok "existing Claude credentials found (no re-login needed)" \
  || warn "no credentials yet - first 'claude' run will ask you to log in"

# --- 5. tmux config ----------------------------------------------------------
step "5/8  tmux config (shared multi-client sessions)"
if [ -f "$HOME/.tmux.conf" ] && grep -q 'window-size latest' "$HOME/.tmux.conf"; then
  skip "~/.tmux.conf already configured"
else
  [ -f "$HOME/.tmux.conf" ] && cp "$HOME/.tmux.conf" "$HOME/.tmux.conf.bak"
  cat > "$HOME/.tmux.conf" <<'TMUXCONF'
# Shared sessions across the Deck, phone, and other machines.
# Size to the most recently active client, so a phone attaching with a tiny
# terminal does not permanently shrink the desktop view.
set  -g window-size latest
setw -g aggressive-resize on

set  -g mouse on
set  -g history-limit 50000
set -sg escape-time 10
set  -g focus-events on

set  -g default-terminal "tmux-256color"
set -ga terminal-overrides ",xterm-256color:Tc,*256col*:Tc"

# Status bar shows how many clients are attached -- handy for confirming
# your phone actually connected.
set  -g status-interval 5
set  -g status-left  "#[bold] #S #[default]"
set  -g status-right " #{session_attached} client(s)  %H:%M "
set  -g status-style "bg=colour236,fg=colour250"
TMUXCONF
  ok "~/.tmux.conf written"
fi

# --- 6. cc launcher ----------------------------------------------------------
step "6/8  cc launcher (shared Claude Code session)"
cat > "$BIN/cc" <<'CCEOF'
#!/usr/bin/env bash
# cc -- attach to (or create) a shared Claude Code tmux session.
#   cc                                        session "claude" in $HOME
#   cc -r                                     start with the resume picker
#   cc infra ~/.code/theprototype-app/infra   named session in a repo
set -uo pipefail

# Inside a Flatpak sandbox (VSCode's integrated terminal) the tmux server is
# NOT the host's -- its socket lives in the sandbox's private /tmp. Re-exec on
# the host so every client shares one server.
if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  exec flatpak-spawn --host "$HOME/.local/bin/cc" "$@"
fi

export PATH="$HOME/.local/bin:$PATH"
export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"

RESUME=""
if [ "${1:-}" = "-r" ] || [ "${1:-}" = "--resume" ]; then RESUME="--resume"; shift; fi

SESSION="${1:-claude}"
DIR="${2:-$HOME}"

if tmux has-session -t "=$SESSION" 2>/dev/null; then
  exec tmux attach-session -t "=$SESSION"
fi
# 'exec bash' keeps the window alive if claude exits, so the session survives.
exec tmux new-session -s "$SESSION" -c "$DIR" "claude $RESUME; exec bash"
CCEOF
chmod +x "$BIN/cc" && ok "$BIN/cc written"

# --- 7. Repos ----------------------------------------------------------------
step "7/8  Org repositories (~/.code/$ORG)"
cat > "$HOME/.code/clone-org.sh" <<'CLONEEOF'
#!/usr/bin/env bash
# Clone every repo from an org into <script dir>/<org>/. Idempotent:
# existing clones are fetched/updated instead of re-cloned.
set -uo pipefail

ORG="${1:-theprototype-app}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$ROOT/$ORG"
mkdir -p "$DEST"
export PATH="$HOME/.local/bin:$PATH"
: "${GH_CONFIG_DIR:=$HOME/.config/gh}"
export GH_CONFIG_DIR

cd "$DEST" || exit 1
if ! gh auth status >/dev/null 2>&1; then
  echo "Not authenticated (GH_CONFIG_DIR=$GH_CONFIG_DIR). Run: gh auth login" >&2
  exit 1
fi

# Per-host protocol; the global default is https even when the host is ssh.
PROTO="$(gh config get git_protocol --host github.com 2>/dev/null)"; PROTO="${PROTO:-https}"
echo "==> Listing repos in $ORG (protocol: $PROTO)"
mapfile -t REPOS < <(gh repo list "$ORG" --limit 1000 --no-archived \
  --json nameWithOwner --jq '.[].nameWithOwner')
[ "${#REPOS[@]}" -eq 0 ] && { echo "No repos found."; exit 1; }
echo "==> ${#REPOS[@]} repo(s) found"

cloned=0; updated=0; failed=0
for r in "${REPOS[@]}"; do
  name="${r##*/}"
  if [ "$PROTO" = "ssh" ]; then url="git@github.com:$r.git"; else url="https://github.com/$r.git"; fi
  if [ -d "$name/.git" ]; then
    [ "$(git -C "$name" remote get-url origin 2>/dev/null)" != "$url" ] && \
      git -C "$name" remote set-url origin "$url"
    if git -C "$name" fetch --all --prune --quiet 2>/dev/null; then
      echo "--- $name: updated"; updated=$((updated+1))
    else echo "--- $name: FETCH FAILED"; failed=$((failed+1)); fi
  else
    if git clone --quiet "$url" "$name" 2>/dev/null; then
      echo "--- $name: cloned"; cloned=$((cloned+1))
    else echo "--- $name: CLONE FAILED"; failed=$((failed+1)); fi
  fi
done
echo; echo "==> cloned: $cloned   updated: $updated   failed: $failed"
CLONEEOF
chmod +x "$HOME/.code/clone-org.sh"; ok "~/.code/clone-org.sh written"

if [ "$DO_CLONE" = 1 ]; then
  if gh auth status >/dev/null 2>&1; then
    bash "$HOME/.code/clone-org.sh" "$ORG" | sed 's/^/    /'
  else
    warn "gh not authenticated - run 'gh auth login' (choose SSH), then:"
    warn "   bash ~/.code/clone-org.sh $ORG"
  fi
else
  skip "--no-clone given"
fi

# --- 8. SSH access -----------------------------------------------------------
step "8/8  SSH access (remote/phone attach)"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys" && chmod 600 "$HOME/.ssh/authorized_keys"
ok "~/.ssh prepared (700 / 600)"

if [ "$DO_SSH" = 0 ]; then
  skip "--no-ssh given"
else
  # NOTE: the password and sshd's config live on the /etc overlay, which is
  # backed by the A/B `var` partition -- NOT home. That is why this step may
  # need repeating after a major SteamOS update, unlike everything above.
  PWSTATE="$(passwd -S "$USER" 2>/dev/null | awk '{print $2}')"
  if [ "$PWSTATE" = "P" ]; then
    ok "password already set for $USER"
  else
    echo
    echo "    A password is required before sudo (and SSH) can work."
    echo "    Set one now:"
    echo
    passwd || die "passwd failed"
    ok "password set"
  fi

  if systemctl is-active --quiet sshd; then
    ok "sshd already running"
  else
    echo
    echo "    Enabling sshd - enter your password at the sudo prompt:"
    echo
    if sudo systemctl enable --now sshd; then ok "sshd enabled and started"
    else warn "could not enable sshd; run: sudo systemctl enable --now sshd"; fi
  fi

  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    if firewall-cmd --list-services 2>/dev/null | grep -qw ssh; then
      ok "firewalld permits ssh"
    else
      warn "firewalld active but ssh not allowed; run:"
      warn "   sudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload"
    fi
  fi
fi

# --- Summary -----------------------------------------------------------------
IP="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)"
cat <<SUMMARY

$(printf '\033[1m==> Done.\033[0m')

  Start or join the shared session, here or over SSH:

      cc                    on this machine
      cc -r                 with the resume picker
      ssh deck@${IP:-<ip>} -t 'bash -lc cc'

  'bash -lc' is required: a plain 'ssh host cc' runs a non-interactive,
  non-login shell, which never sources ~/.bashrc and so cannot find cc.

  Client-side ~/.ssh/config (Windows, phone, other machines):

      Host deck
          HostName ${IP:-<ip>}
          User $USER
          RequestTTY yes
          RemoteCommand bash -lc cc

      Host deck-shell
          HostName ${IP:-<ip>}
          User $USER

  Not automated (deliberately):
    - gh auth login          browser/device flow; pick SSH as the protocol
    - claude login           only if ~/.claude/.credentials.json is absent
    - ssh public keys        append to ~/.ssh/authorized_keys, then set
                             PasswordAuthentication no in /etc/ssh/sshd_config
SUMMARY
