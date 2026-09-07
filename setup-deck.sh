#!/usr/bin/env bash
# setup-deck.sh -- rebuild this machine's dev environment after a SteamOS
# reset, reimage, or major update. Idempotent: safe to re-run any time;
# anything already in place is reported and skipped.
#
#   bash ~/.code/scripts/setup-deck.sh              full run
#   bash ~/.code/scripts/setup-deck.sh --no-ssh     skip the passwd + sshd steps
#   bash ~/.code/scripts/setup-deck.sh --no-clone   skip cloning the org repos
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
step "1/15  Shell environment (~/.bashrc)"
need_path=1; need_gh=1; need_node=1
grep -q '\.local/bin'   "$HOME/.bashrc" 2>/dev/null && need_path=0
grep -q 'GH_CONFIG_DIR'  "$HOME/.bashrc" 2>/dev/null && need_gh=0
grep -q 'local/node/bin' "$HOME/.bashrc" 2>/dev/null && need_node=0
if [ "$need_path" = 0 ] && [ "$need_gh" = 0 ] && [ "$need_node" = 0 ]; then
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
    if [ "$need_node" = 1 ]; then
      echo '# Node toolchain: node/npm/npx live here, NOT in ~/.local/bin.'
      echo '# npm and npx are /usr/bin/env node scripts and cannot start without this.'
      echo 'case ":$PATH:" in'
      echo '  *":$HOME/.local/node/bin:"*) ;;'
      echo '  *) [ -d "$HOME/.local/node/bin" ] && export PATH="$HOME/.local/node/bin:$PATH" ;;'
      echo 'esac'
    fi
    echo
    cat "$HOME/.bashrc" 2>/dev/null
  } > "$HOME/.bashrc.new" && mv "$HOME/.bashrc.new" "$HOME/.bashrc"
  [ "$need_path" = 1 ] && ok "PATH prepended"
  [ "$need_gh"   = 1 ] && ok "GH_CONFIG_DIR prepended"
  [ "$need_node" = 1 ] && ok "node PATH prepended"
  ok "backup at ~/.bashrc.bak"
fi
export PATH="$BIN:$PATH"
export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"
[ -d "$HOME/.local/node/bin" ] && export PATH="$HOME/.local/node/bin:$PATH"

# --- 2. Preinstalled tools ---------------------------------------------------
step "2/15  Checking preinstalled tools"
for t in git tmux curl jq python3 ssh; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t $(command -v $t)"
  else warn "$t MISSING - unexpected on SteamOS"; fi
done

# --- 3. Cloud CLIs: terraform + aws ------------------------------------------
# Both live under $HOME (the A/B rootfs would lose a pacman install). Terraform
# is verified against HashiCorp's SHA256SUMS like gh above; the AWS CLI v2
# bundle installs into ~/.local/aws-cli with a symlink in ~/.local/bin.
# Used by: theprototype-app/infra (EC2 root module on the Windows PC, the
# infra/cloudflare module from here; state in the S3 bucket
# theprototype-tfstate-<account>) and the aws ssm/s3 helper scripts.
step "3/15  Cloud CLIs (terraform, aws)"
if [ -x "$BIN/terraform" ]; then
  skip "terraform $("$BIN/terraform" version | head -1 | awk '{print $2}') already at $BIN/terraform"
else
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  VER="$(curl -s https://checkpoint-api.hashicorp.com/v1/check/terraform | jq -r .current_version)"
  [ -n "$VER" ] && [ "$VER" != "null" ] || die "could not determine latest terraform version"
  ok "latest is v$VER, downloading"
  curl -fL --progress-bar -o "$TMP/tf.zip" \
    "https://releases.hashicorp.com/terraform/${VER}/terraform_${VER}_linux_amd64.zip" \
    || die "download failed"
  curl -fsL -o "$TMP/sums" \
    "https://releases.hashicorp.com/terraform/${VER}/terraform_${VER}_SHA256SUMS" \
    || die "checksum download failed"
  EXP="$(grep "terraform_${VER}_linux_amd64.zip" "$TMP/sums" | awk '{print $1}')"
  ACT="$(sha256sum "$TMP/tf.zip" | awk '{print $1}')"
  [ "$EXP" = "$ACT" ] || die "CHECKSUM MISMATCH - refusing to install"
  ok "sha256 verified"
  unzip -oq "$TMP/tf.zip" -d "$TMP" && install -m 755 "$TMP/terraform" "$BIN/terraform"
  ok "terraform $("$BIN/terraform" version | head -1 | awk '{print $2}') installed"
fi
if [ -x "$BIN/aws" ]; then
  skip "aws $("$BIN/aws" --version 2>&1 | awk '{print $1}' | cut -d/ -f2) already at $BIN/aws"
else
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  ok "downloading the AWS CLI v2 bundle"
  curl -fL --progress-bar -o "$TMP/awscli.zip" \
    "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" || die "download failed"
  unzip -q "$TMP/awscli.zip" -d "$TMP" \
    && "$TMP/aws/install" --install-dir "$HOME/.local/aws-cli" --bin-dir "$BIN" --update >/dev/null \
    || die "aws installer failed"
  ok "aws $("$BIN/aws" --version 2>&1 | awk '{print $1}' | cut -d/ -f2) installed"
fi
[ -f "$HOME/.aws/credentials" ] && ok "aws credentials present (~/.aws)" \
  || warn "no ~/.aws/credentials - run: aws configure   (IAM user, region eu-central-1)"

# --- 4. GitHub CLI -----------------------------------------------------------
step "4/15  GitHub CLI (gh)"
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

# --- 5. Claude Code CLI ------------------------------------------------------
step "5/15  Claude Code CLI"
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

# Wait out a usage limit and carry on, instead of stopping the session dead.
# Applies to sessions STARTED AFTER this is written -- a running claude will
# not pick it up, so restart any open session after a first-time run.
CS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"
[ -f "$CS" ] || echo '{}' > "$CS"
if [ "$(jq -r '.autoContinueAtUsageLimit // false' "$CS" 2>/dev/null)" = "true" ]; then
  skip "autoContinueAtUsageLimit already enabled"
elif jq '.autoContinueAtUsageLimit = true' "$CS" > "$CS.new" 2>/dev/null && mv "$CS.new" "$CS"; then
  ok "autoContinueAtUsageLimit enabled (waits for the reset, then continues)"
else
  rm -f "$CS.new"
  warn "could not update $CS - set autoContinueAtUsageLimit to true by hand"
fi

# Unattended sessions (the watchdog resumes claude with nobody at the keyboard,
# scheduled windows run overnight) cannot answer a permission prompt, so this
# machine runs Claude Code in bypassPermissions mode. Set by hand 2026-09-06;
# kept here so a reimage restores it. Same "restart open sessions" caveat.
if [ "$(jq -r '.defaultMode // ""' "$CS" 2>/dev/null)" = "bypassPermissions" ]; then
  skip "defaultMode already bypassPermissions"
elif jq '.defaultMode = "bypassPermissions"' "$CS" > "$CS.new" 2>/dev/null && mv "$CS.new" "$CS"; then
  ok "defaultMode set to bypassPermissions (unattended sessions never block on a prompt)"
else
  rm -f "$CS.new"
  warn "could not update $CS - set defaultMode to bypassPermissions by hand"
fi

# --- 6. tmux config ----------------------------------------------------------
step "6/15  tmux config (shared multi-client sessions)"
if [ -f "$HOME/.tmux.conf" ] && grep -q 'window-size latest' "$HOME/.tmux.conf"; then
  skip "~/.tmux.conf already configured"
else
  [ -f "$HOME/.tmux.conf" ] && cp "$HOME/.tmux.conf" "$HOME/.tmux.conf.bak"
  if [ -f "$HOME/.code/scripts/tmux.conf" ]; then
    # The versioned copy is canonical. The heredoc below stays as the
    # fallback for a machine being rebuilt before ~/.code exists.
    cp "$HOME/.code/scripts/tmux.conf" "$HOME/.tmux.conf"
  else
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
  fi
  ok "~/.tmux.conf written"
fi

# --- 7. cc launcher ----------------------------------------------------------
step "7/15  cc launcher (shared Claude Code session)"
cat > "$BIN/cc" <<'CCEOF'
#!/usr/bin/env bash
# cc -- attach to (or create) a shared Claude Code tmux session.
#   cc                                        session "claude" in $HOME
#   cc -r                                     start with the resume picker
#   cc infra ~/.code/theprototype-app/infra   named session in a repo
#   cc -w                                     the WORK account (~/.claude-work)
#   cc -P acme                                any account (~/.claude-acme)
#   cc -w infra ~/path                        named session on the work account
#
# ONE ACCOUNT PER SESSION. A profile picks the Claude config dir, and every
# path that belongs to an account follows it: the tmux session name, the
# schedules folder, the backups folder, the handovers folder, the watchdog's
# state and its usage cache. The default account is unsuffixed, so `cc` with no
# flag is byte-for-byte what it has always been.
#
# The config dir is exported into the SESSION environment (-e), not just this
# process, so every window opened later -- by hand, by the dashboard, or by the
# watchdog launching a scheduled window -- inherits the right account instead
# of quietly falling back to the default one.
set -uo pipefail

# Inside a Flatpak sandbox (VSCode's integrated terminal) the tmux server is
# NOT the host's -- its socket lives in the sandbox's private /tmp. Re-exec on
# the host so every client shares one server.
if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  exec flatpak-spawn --host "$HOME/.local/bin/cc" "$@"
fi

export PATH="$HOME/.local/bin:$PATH"
export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"

. "$HOME/.code/scripts/profile.sh"

RESUME=""
PROFILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -r|--resume)  RESUME="--resume"; shift ;;
    -w|--work)    PROFILE="work"; shift ;;
    -P|--profile) [ -n "${2:-}" ] || { echo "--profile needs a name" >&2; exit 2; }
                  PROFILE="$2"; shift 2 ;;
    -h|--help)    sed -n '2,9p' "$0"; exit 0 ;;
    --)           shift; break ;;
    -*)           echo "unknown option: $1" >&2; exit 2 ;;
    *)            break ;;
  esac
done

code_use_profile "$PROFILE"
export CLAUDE_CONFIG_DIR="$CODE_CONFIG_DIR"

# A NAMED session is suffixed too. That is the point of the exercise: two
# accounts working the same repo would otherwise both want the session `infra`,
# and whichever got there first would silently adopt the other's windows.
SESSION="${1:-claude}"
[ -n "$CODE_SUFFIX" ] && SESSION="$SESSION$CODE_SUFFIX"
DIR="${2:-$HOME}"

# The account's own folders, made on first use. Cheap, idempotent, and it means
# a fresh profile never has a window fail because a folder it writes to is
# missing -- the handover folder in particular is written to by a wind-down,
# which is exactly when you least want a second failure.
mkdir -p "$CODE_SCHEDULES/templates" "$CODE_BACKUPS" "$CODE_HANDOVERS/done"

if [ ! -d "$CODE_CONFIG_DIR" ]; then
  echo "no config dir at $CODE_CONFIG_DIR -- creating it; you will be asked to log in." >&2
  mkdir -p "$CODE_CONFIG_DIR"
fi

if tmux has-session -t "=$SESSION" 2>/dev/null; then
  exec tmux attach-session -t "=$SESSION"
fi

# A NEW session gets two windows: 0 = the live status dashboard (the landing
# page), 1 = Claude. Attaching lands on 0, so the state of the machine is the
# first thing you see; Ctrl-b 1 switches to Claude. Re-attaching to an
# existing session returns you to whichever window you left, untouched.
#
# 'exec bash' keeps each window alive if its program exits, so a stray Ctrl-C
# never destroys the session.
STATUS="$HOME/.code/scripts/deck-status.sh"
tmux new-session -d -s "$SESSION" -c "$DIR" -n status \
  -e "CLAUDE_CONFIG_DIR=$CODE_CONFIG_DIR" \
  "if [ -x \"$STATUS\" ]; then \"$STATUS\"; else echo 'deck-status.sh not found'; fi; exec bash"
tmux new-window -t "=$SESSION" -c "$DIR" -n claude \
  -e "CLAUDE_CONFIG_DIR=$CODE_CONFIG_DIR" \
  "claude $RESUME; exec bash"
tmux select-window -t "=$SESSION:0"
exec tmux attach-session -t "=$SESSION"
CCEOF
chmod +x "$BIN/cc" && ok "$BIN/cc written"

# --- 8. Repos ----------------------------------------------------------------
step "8/15  Org repositories (~/.code/$ORG)"
mkdir -p "$HOME/.code/scripts"
cat > "$HOME/.code/scripts/clone-org.sh" <<'CLONEEOF'
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
chmod +x "$HOME/.code/scripts/clone-org.sh"; ok "~/.code/scripts/clone-org.sh written"

if [ "$DO_CLONE" = 1 ]; then
  if gh auth status >/dev/null 2>&1; then
    bash "$HOME/.code/scripts/clone-org.sh" "$ORG" | sed 's/^/    /'
  else
    warn "gh not authenticated - run 'gh auth login' (choose SSH), then:"
    warn "   bash ~/.code/scripts/clone-org.sh $ORG"
  fi
else
  skip "--no-clone given"
fi

# --- 9. SSH access -----------------------------------------------------------
step "9/15  SSH access (remote/phone attach)"
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

# --- 10. Passwordless sudo ----------------------------------------------------
step "10/15  Passwordless sudo (needs the password once)"
# Deliberately BEFORE the three steps that write /etc: with this in place they
# run unattended, here and from after-update.sh over a bare ssh command.
if [ "$DO_SSH" = 0 ]; then
  skip "--no-ssh given"
elif [ -x "$HOME/.code/scripts/apply-sudo.sh" ]; then
  "$HOME/.code/scripts/apply-sudo.sh"
else
  warn "~/.code/scripts/apply-sudo.sh missing - later steps will prompt"
fi

# --- Summary -----------------------------------------------------------------
# --- 11. Playwright browsers --------------------------------------------------
step "11/15  Playwright browsers (e2e suites)"
CORE="$HOME/.code/$ORG/core"
if ! command -v node >/dev/null 2>&1; then
  warn "node not on PATH - open a new shell, then re-run"
elif [ ! -d "$CORE/node_modules" ]; then
  warn "$CORE/node_modules missing - run npm install there first, then re-run"
elif ls "$HOME/.cache/ms-playwright" 2>/dev/null | grep -q chromium-; then
  skip "chromium already installed"
else
  # Playwright ships no SteamOS build and falls back to its ubuntu24.04 one.
  # That binary runs fine here - verified with a real headless launch.
  if ( cd "$CORE" && npx playwright install chromium ); then
    ok "chromium installed"
  else
    warn "playwright install failed - run it by hand in $CORE"
  fi
fi

# --- 12. e2e hosts mapping ---------------------------------------------------
step "12/15  e2e hosts mapping (needs sudo)"
# Its own helper, because a SteamOS update REPLACES the root partition and
# reverts /etc/hosts - after-update.sh re-runs this same script.
if [ -x "$HOME/.code/scripts/apply-hosts.sh" ]; then
  "$HOME/.code/scripts/apply-hosts.sh"
else
  warn "~/.code/scripts/apply-hosts.sh missing - e2e cannot resolve theprototype.app"
fi

# --- 13. tmux session persistence --------------------------------------------
step "13/15  tmux session persistence (needs sudo)"
# Its own helper for the same reason as the hosts step: it writes /etc and /var
# state that a SteamOS update reverts, so after-update.sh re-runs it. Without
# it, logind kills the whole tmux server -- every window with it -- the moment
# your last SSH session closes. See apply-logind.sh's header for the evidence.
if [ -x "$HOME/.code/scripts/apply-logind.sh" ]; then
  "$HOME/.code/scripts/apply-logind.sh"
else
  warn "~/.code/scripts/apply-logind.sh missing - tmux will die on disconnect"
fi

# --- 14. Dashboard runtime ---------------------------------------------------
step "14/15  Dashboard runtime (rich)"
# deck-status.sh renders through rich when this venv exists and falls back to
# its own bash renderer when it does not, so this step is an optimisation and
# never a hard dependency. 27 MB, kept out of git.
VENV="$HOME/.code/scripts/.venv"
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import rich' 2>/dev/null; then
  skip "venv already usable"
elif ! command -v python3 >/dev/null 2>&1; then
  warn "python3 missing - deck-status.sh will use its bash renderer"
else
  rm -rf "$VENV"
  if python3 -m venv "$VENV" >/dev/null 2>&1 && "$VENV/bin/pip" install --quiet rich >/dev/null 2>&1; then
    ok "rich installed ($(du -sh "$VENV" 2>/dev/null | cut -f1))"
  else
    warn "could not build the venv - deck-status.sh will use its bash renderer"
  fi
fi


# --- 15. Usage-limit watchdog ------------------------------------------------
step "15/15  Usage-limit watchdog"
# Installs a systemd USER service, so it depends on the lingering that step 12
# turns on. Without that it would die at logout -- the same failure it exists
# to work around, one layer down.
if [ -x "$HOME/.code/scripts/claude-watchdog.sh" ]; then
  "$HOME/.code/scripts/claude-watchdog.sh" --install | sed 's/^/    /'
else
  warn "~/.code/scripts/claude-watchdog.sh missing - a limited window will sit idle"
fi

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
