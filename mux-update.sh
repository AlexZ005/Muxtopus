#!/usr/bin/env bash
# mux-update.sh -- notice a new release, read what is in it, take it, put it back.
#
#   mux-update.sh --check [--force]   ask GitHub what the newest release is
#   mux-update.sh --status            what is installed, what is out, how old the answer is
#   mux-update.sh --notes [X.Y.Z]     that release's notes (cached; fetched once)
#   mux-update.sh --stage             download and verify it, install nothing
#   mux-update.sh --apply [--yes]     install it, keeping the tree it replaces
#   mux-update.sh --rollback [--yes]  put that kept tree back
#
# WHAT THIS IS ALLOWED TO DO, AND ALL OF IT. The check is one HTTPS request
# that follows the `releases/latest` redirect and reads the tag out of the
# URL it lands on: no API token, no query string, nothing about this machine
# in it, and no request at all when MUXTOPUS_UPDATE_MODE=off. Nothing is
# downloaded until --stage or --apply, and nothing is INSTALLED without
# --yes or a hand on a confirm row. Every path written is the one get.sh
# already writes: ~/.local/lib/muxtopus and what install.sh puts in $HOME.
#
# IT INSTALLS BY RUNNING THE RELEASE'S OWN get.sh, never by unpacking a
# tarball itself. That file carries the sha256 of its release's tarball,
# computed from the tag at release time, so the chain a self-updater has to
# get right is already written down and already tested (tests/test_release.sh).
# What this adds on top is one link: get.sh is itself checked against the
# SHA256SUMS published beside it before it is run. Both come over TLS from
# the same release, so this catches a truncated or corrupted download, not a
# hostile GitHub -- docs/updates.md says so plainly rather than implying more.
#
# IT REFUSES TO TOUCH A GIT CHECKOUT. A checkout runs in place and `git pull`
# is its upgrade; overwriting one with a tarball would throw away whatever was
# being worked on in it. The marker is .muxtopus-release, which get.sh writes
# and a checkout never has.
#
# THE ANSWER IS SHARED BY EVERY ACCOUNT. There is one installed tree, so the
# check, its cache and its clock live in MUX_UPDATE_DIR, which has no account
# suffix. Whichever watchdog gets there first does the request; the others
# find it fresh and return without a syscall that leaves the machine.
set -uo pipefail

_self="${BASH_SOURCE[0]}"
_dir="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck disable=SC1091
. "$_dir/profile.sh"

REPO="${MUXTOPUS_REPO:-AlexZ005/Muxtopus}"
# Every URL this script can build, in one place, so a test can point the whole
# thing at a directory of files (see tests/test_update.sh) without a network.
BASE="${MUXTOPUS_UPDATE_BASE:-https://github.com/$REPO/releases}"
API="${MUXTOPUS_UPDATE_API:-https://api.github.com/repos/$REPO}"

MODE=""
FORCE=0
YES=0
NOTES_VER=""
PROFILE=""
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check)     MODE=check; shift ;;
    --status)    MODE=status; shift ;;
    --notes)     MODE=notes
                 case "${2:-}" in -*|"") ;; *) NOTES_VER="$2"; shift ;; esac
                 shift ;;
    --stage)     MODE=stage; shift ;;
    --apply)     MODE=apply; shift ;;
    --rollback)  MODE=rollback; shift ;;
    --force)     FORCE=1; shift ;;
    -y|--yes)    YES=1; shift ;;
    -q|--quiet)  QUIET=1; shift ;;
    --profile=*) PROFILE="${1#--profile=}"; shift ;;
    -P|--profile) [ -n "${2:-}" ] || { echo "mux-update.sh: --profile needs a name" >&2; exit 2; }
                 PROFILE="$2"; shift 2 ;;
    -h|--help)   sed -n '2,9p' "$0"; exit 0 ;;
    *)           echo "mux-update.sh: unknown option: $1" >&2; exit 2 ;;
  esac
done

# The config layers only; no account paths are needed here, because nothing
# this script reads or writes belongs to an account -- there is one tree.
mux_load_config "$PROFILE"

DIR="$MUX_UPDATE_DIR"
STATE="$DIR/state"
LOG="$DIR/update.log"
STAGE="$DIR/staged"

# The tree that is installed, and the one it replaced. MUXTOPUS_DIR is what
# every other script means by "the code", so it is what gets replaced.
LIB="${MUXTOPUS_DIR:-$_dir}"
PREV="$LIB.prev"

MODE_SET="${MUXTOPUS_UPDATE_MODE:-notify}"
EVERY="${MUXTOPUS_UPDATE_EVERY:-24}"
CHANNEL="${MUXTOPUS_UPDATE_CHANNEL:-stable}"

say()  { [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }
warn() { printf 'mux-update: %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }
log()  { mkdir -p "$DIR"; printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

installed() { tr -d '[:space:]' < "$LIB/VERSION" 2>/dev/null || echo "?"; }

# ------------------------------------------------------------------- state
# KEY=value, rewritten whole through a temp file: it is this script's own
# file, small, and read by a shell, by python and by awk. Nothing in it is
# secret and nothing in it is authoritative about the INSTALL -- the installed
# version is always read from $LIB/VERSION, so a stale or deleted state file
# makes the next check slow, never wrong.
state_get() {
  [ -f "$STATE" ] || return 0
  sed -n "s/^$1=//p" "$STATE" | tail -1
}

state_put() {
  local k v tmp had=0
  mkdir -p "$DIR" || return 1
  tmp="$STATE.tmp.$$"
  : > "$tmp"
  if [ -f "$STATE" ]; then
    while IFS= read -r line; do
      had=0
      for kv in "$@"; do
        k="${kv%%=*}"
        [ "${line%%=*}" = "$k" ] && { had=1; break; }
      done
      [ "$had" = 1 ] || printf '%s\n' "$line" >> "$tmp"
    done < "$STATE"
  fi
  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    printf '%s=%s\n' "$k" "$v" >> "$tmp"
  done
  mv "$tmp" "$STATE"
}

# ------------------------------------------------------------- the network
# One fetcher, so "what did this script ask the internet for" is one grep.
# curl first because it is what get.sh needs anyway; wget is the fallback for
# a machine that only has that.
fetch() {
  local url="$1" out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 20 "$url" -o "$out" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -q -T 20 -O "$out" "$url" 2>/dev/null
  else
    return 3
  fi
}

# THE NEWEST TAG, without an API call on the stable channel: GitHub redirects
# releases/latest to releases/tag/vX.Y.Z, and the tag is the last segment of
# where it lands. -o /dev/null throws the page away; only the URL is read.
# A prerelease channel cannot be done that way -- `latest` skips prereleases
# by definition -- so it asks the API, which is 60 requests an hour without a
# token and is being asked once a day.
resolve_tag() {
  local url tag body
  if [ -n "${MUXTOPUS_UPDATE_TAG_URL:-}" ]; then
    body="$(mktemp)" || return 1
    fetch "$MUXTOPUS_UPDATE_TAG_URL" "$body" || { rm -f "$body"; return 1; }
    tag="$(tr -d '[:space:]' < "$body")"; rm -f "$body"
    printf '%s' "$tag"; return 0
  fi
  if [ "$CHANNEL" = prerelease ]; then
    command -v jq >/dev/null 2>&1 || return 1
    body="$(mktemp)" || return 1
    fetch "$API/releases?per_page=10" "$body" || { rm -f "$body"; return 1; }
    tag="$(jq -r 'map(select(.draft | not)) | .[0].tag_name // empty' < "$body" 2>/dev/null)"
    rm -f "$body"
    [ -n "$tag" ] || return 1
    printf '%s' "$tag"; return 0
  fi
  command -v curl >/dev/null 2>&1 || return 1
  url="$(curl -fsSL --max-time 20 -o /dev/null -w '%{url_effective}' "$BASE/latest" 2>/dev/null)" || return 1
  tag="${url##*/}"
  case "$tag" in v[0-9]*) printf '%s' "$tag" ;; *) return 1 ;; esac
}

# Is $1 newer than $2? `sort -V` is the same comparison pacman and dpkg reach
# for, and it gets 5.10.0 > 5.9.0 right, which a string compare does not.
newer_than() {
  [ "$1" = "$2" ] && return 1
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}

# --------------------------------------------------------------- the check
do_check() {
  local now last tag latest cur
  cur="$(installed)"
  now="$(date +%s)"
  if [ "$MODE_SET" = off ] && [ "$FORCE" != 1 ]; then
    state_put "STATE=off" "CURRENT=$cur"
    say "update checks are off (MUXTOPUS_UPDATE_MODE=off)"
    return 0
  fi
  last="$(state_get CHECKED_AT)"
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  # THE SHARED CLOCK. Every account's watchdog calls this on every pass; all
  # but the first return here, having touched nothing and asked nobody.
  if [ "$FORCE" != 1 ] && [ $(( now - last )) -lt $(( EVERY * 3600 )) ]; then
    return 0
  fi
  if ! tag="$(resolve_tag)"; then
    # A machine that is offline is the ordinary case, not an error worth a
    # notification: the stamp moves so it is not retried every thirty
    # seconds, the previous answer is kept, and the reason is on the row.
    state_put "CHECKED_AT=$now" "ERROR=could not reach $REPO"
    say "could not reach $REPO -- keeping what was known"
    return 1
  fi
  latest="${tag#v}"
  state_put "CHECKED_AT=$now" "CURRENT=$cur" "LATEST=$latest" "TAG=$tag" \
            "CHANNEL=$CHANNEL" "ERROR="
  if newer_than "$latest" "$cur"; then
    # STAGED SURVIVES A RE-CHECK of the same version: `download` mode stages
    # once and a later check must not undo that and make it download again.
    [ "$(state_get STATE)" = "staged" ] && [ "$(state_get STAGED)" = "$latest" ] \
      || state_put "STATE=available"
    log "available: $latest (installed $cur, channel $CHANNEL)"
    say "muxtopus $latest is out -- this is $cur"
    [ "$MODE_SET" = download ] && do_stage
    return 0
  fi
  state_put "STATE=uptodate"
  say "up to date: $cur"
  return 0
}

# --------------------------------------------------------------- the notes
notes_path() { printf '%s/notes-%s.md' "$DIR" "$1"; }

do_notes() {
  local v="${1:-}" f body
  [ -n "$v" ] || v="$(state_get LATEST)"
  [ -n "$v" ] || die "nothing to show notes for -- run --check first"
  f="$(notes_path "$v")"
  if [ ! -s "$f" ]; then
    mkdir -p "$DIR"
    body="$(mktemp)" || die "no temp file"
    if fetch "$API/releases/tags/v$v" "$body" && command -v jq >/dev/null 2>&1; then
      jq -r '.body // empty' < "$body" > "$f.tmp" 2>/dev/null
    fi
    rm -f "$body"
    if [ -s "$f.tmp" ]; then
      mv "$f.tmp" "$f"
    else
      rm -f "$f.tmp"
      # No API, no jq, or a release with an empty body: say where to read it
      # rather than print nothing and look broken.
      printf 'Release notes for muxtopus %s could not be fetched.\n\n%s/tag/v%s\n' \
             "$v" "$BASE" "$v" > "$f"
    fi
  fi
  cat "$f"
}

# One line of it, for a phone message or a menu row.
notes_headline() {
  local v="${1:-}" f
  f="$(notes_path "$v")"
  [ -s "$f" ] || return 0
  grep -m1 -v '^\s*$' "$f" 2>/dev/null | sed -e 's/^#\+ *//' -e 's/[*_`]//g' | cut -c1-120
}

# -------------------------------------------------------------- the staging
# get.sh and the sums beside it, checked against each other. The tarball is
# not fetched here: get.sh does that, with the sha it was born with, and
# doing it twice would only mean two chances to get the check wrong.
do_stage() {
  local v tag tmp want got
  v="$(state_get LATEST)"; tag="$(state_get TAG)"
  [ -n "$v" ] || die "nothing staged and nothing known -- run --check first"
  [ -n "$tag" ] || tag="v$v"
  mkdir -p "$STAGE" || die "cannot make $STAGE"
  tmp="$(mktemp -d)" || die "no temp dir"
  # shellcheck disable=SC2064
  trap "rm -rf -- '${tmp:?}'" RETURN

  fetch "$BASE/download/$tag/get.sh" "$tmp/get.sh" \
    || { state_put "ERROR=could not download get.sh for $tag"; die "could not download get.sh for $tag"; }
  if ! fetch "$BASE/download/$tag/SHA256SUMS" "$tmp/SHA256SUMS"; then
    state_put "ERROR=no SHA256SUMS for $tag"
    die "$tag publishes no SHA256SUMS -- refusing to run an unchecked installer"
  fi
  want="$(awk '$2 == "get.sh" || $2 == "*get.sh" {print $1}' "$tmp/SHA256SUMS" | tail -1)"
  [ -n "$want" ] || { state_put "ERROR=SHA256SUMS names no get.sh"; die "SHA256SUMS for $tag names no get.sh"; }
  if command -v sha256sum >/dev/null 2>&1; then
    got="$(sha256sum "$tmp/get.sh" | cut -d' ' -f1)"
  elif command -v shasum >/dev/null 2>&1; then
    got="$(shasum -a 256 "$tmp/get.sh" | cut -d' ' -f1)"
  else
    die "no sha256sum or shasum to check the installer with"
  fi
  if [ "$got" != "$want" ]; then
    state_put "ERROR=get.sh checksum mismatch for $tag"
    log "REFUSED $tag: get.sh sha256 $got, SHA256SUMS says $want"
    die "get.sh for $tag does not match its SHA256SUMS -- nothing installed"
  fi
  rm -f "$STAGE/get.sh" "$STAGE/SHA256SUMS"
  mv "$tmp/get.sh" "$STAGE/get.sh"
  mv "$tmp/SHA256SUMS" "$STAGE/SHA256SUMS"
  chmod +x "$STAGE/get.sh"
  state_put "STATE=staged" "STAGED=$v" "ERROR="
  log "staged $tag (get.sh sha256 ok)"
  say "staged muxtopus $v -- sha256 of its installer checked against SHA256SUMS"
  return 0
}

# --------------------------------------------------------------- the apply
# What install.sh must be told so an update does not quietly add what this
# machine chose not to have. The watchdog is the one that matters: a machine
# installed with --no-watchdog has no unit, and an update must not give it one.
install_flags() {
  local unit out=""
  unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  if ! ls "$unit"/claude-watchdog*.service >/dev/null 2>&1; then
    out="--no-watchdog"
  fi
  # ...and a machine that has no venv chose not to have one (--no-venv, or a
  # python too old to build it). An update is not the moment to start
  # downloading packages nobody asked for.
  [ -d "$LIB/.venv" ] || out="$out --no-venv"
  printf '%s' "$out"
}

# EVERY ACCOUNT'S DAEMON, not this one's. The tree they all run has just been
# replaced underneath them; --reload is a SIGHUP the daemon answers by
# re-execing itself, so each one comes back on the new code having finished
# the pass it was in. A daemon that is not running is left not running.
reload_watchdogs() {
  local p n=0
  while IFS= read -r p; do
    if [ -n "$p" ]; then
      "$LIB/claude-watchdog.sh" --profile "$p" --reload >/dev/null 2>&1 && n=$(( n + 1 ))
    else
      "$LIB/claude-watchdog.sh" --reload >/dev/null 2>&1 && n=$(( n + 1 ))
    fi
  done < <(mux_profiles)
  printf '%s' "$n"
}

do_apply() {
  local v cur out rc got flags n
  cur="$(installed)"
  v="$(state_get LATEST)"
  [ -n "$v" ] || die "nothing to apply -- run --check first"
  newer_than "$v" "$cur" || die "$cur is already the newest release ($v)"

  # THE TWO REFUSALS, before anything is downloaded.
  [ -e "$LIB/.git" ] && die "$LIB is a git checkout: \`git -C $LIB pull\` is its update"
  [ -f "$LIB/.muxtopus-release" ] \
    || die "$LIB was not installed by get.sh (no .muxtopus-release): update it the way it was installed"
  [ -w "$(dirname "$LIB")" ] || die "$(dirname "$LIB") is not writable"

  if [ "$YES" != 1 ]; then
    printf 'Install muxtopus %s over %s in %s? [y/N] ' "$v" "$cur" "$LIB"
    read -r a
    case "$a" in y|Y|yes|YES) ;; *) say "left alone"; return 1 ;; esac
  fi

  [ -f "$STAGE/get.sh" ] && [ "$(state_get STAGED)" = "$v" ] || do_stage || return 1

  say "installing muxtopus $v ..."
  flags="$(install_flags)"
  out="$DIR/install-$v.log"
  # MUXTOPUS_LIB is what get.sh replaces, and it is told explicitly: the tree
  # being updated is the one this script was run from, never whatever the
  # default happens to be on this machine.
  # shellcheck disable=SC2086
  MUXTOPUS_LIB="$LIB" bash "$STAGE/get.sh" $flags > "$out" 2>&1
  rc=$?
  got="$(installed)"
  if [ "$rc" != 0 ] || [ "$got" != "$v" ]; then
    state_put "STATE=failed" "ERROR=install failed (see $out)"
    log "FAILED $v: rc=$rc, VERSION now $got"
    warn "the install failed -- $LIB still says $got. The log is $out:"
    tail -15 "$out" >&2
    [ -d "$PREV" ] && warn "the tree it would have replaced is still at $PREV (--rollback puts it back)"
    return 1
  fi
  state_put "STATE=applied" "CURRENT=$v" "APPLIED_AT=$(date +%s)" "ERROR=" \
            "PREV=$cur" "STAGED="
  log "applied $v (was $cur)"
  n="$(reload_watchdogs)"
  say "muxtopus $v is installed. $n watchdog(s) reloaded onto it."
  say "The dashboard is still running the old code: press R there, or it says so in its header."
  [ -d "$PREV" ] && say "The $cur tree is kept at $PREV -- \`mux-update.sh --rollback\` puts it back."
  return 0
}

# ------------------------------------------------------------- the rollback
# The mirror image, and the reason the tree is kept at all: an update that
# breaks this machine is a move and a reload, not a hunt for the old tag.
do_rollback() {
  local cur back swap n
  cur="$(installed)"
  [ -d "$PREV" ] || die "nothing kept at $PREV -- install the version you want with its own get.sh"
  back="$(tr -d '[:space:]' < "$PREV/VERSION" 2>/dev/null)"
  [ -n "$back" ] || die "$PREV has no VERSION file -- it is not a muxtopus tree"
  [ -e "$LIB/.git" ] && die "$LIB is a git checkout: nothing here put it there"

  if [ "$YES" != 1 ]; then
    printf 'Put muxtopus %s back in place of %s? [y/N] ' "$back" "$cur"
    read -r a
    case "$a" in y|Y|yes|YES) ;; *) say "left alone"; return 1 ;; esac
  fi

  swap="$LIB.rollback.$$"
  mv "$LIB" "$swap" || die "could not move $LIB aside"
  if ! mv "$PREV" "$LIB"; then
    mv "$swap" "$LIB"
    die "could not move $PREV into place -- nothing changed"
  fi
  # THE VENV GOES WITH THE PATH, not with the tree: get.sh carried it forward
  # into the version being rolled back FROM, so it has to come back too, or
  # the dashboard falls to its bash renderer until somebody notices.
  if [ ! -d "$LIB/.venv" ] && [ -d "$swap/.venv" ]; then
    mv "$swap/.venv" "$LIB/.venv"
  fi
  # The tree we just left becomes the one to roll FORWARD to, so this is
  # undoable exactly once in each direction, which is what a rollback is for.
  mv "$swap" "$PREV"
  # install.sh again, from the tree now in place: the unit file, the config
  # template and the venv are all written by it, and the older release may
  # want them its own way.
  bash "$LIB/install.sh" $(install_flags) > "$DIR/rollback-$back.log" 2>&1 \
    || warn "the rolled-back tree is in place but its install.sh complained: $DIR/rollback-$back.log"
  state_put "STATE=rolledback" "CURRENT=$back" "PREV=$cur" "APPLIED_AT=$(date +%s)" "ERROR="
  log "rolled back to $back (from $cur)"
  n="$(reload_watchdogs)"
  say "muxtopus $back is back in $LIB. $n watchdog(s) reloaded onto it."
  say "Press R in the dashboard to reload it too."
  # A rolled-back machine must not be handed the same update by the next
  # check. The clock is left where it is and the state says what happened;
  # the row in the menu reads "<new> available" again only after the user
  # has asked for a check, which is the honest answer -- it IS available.
  return 0
}

# --------------------------------------------------------------- the status
do_status() {
  local cur latest st at ago
  cur="$(installed)"
  latest="$(state_get LATEST)"
  st="$(state_get STATE)"
  at="$(state_get CHECKED_AT)"
  case "$at" in ''|*[!0-9]*) at=0 ;; esac
  if [ "$at" -gt 0 ]; then
    ago=$(( ( $(date +%s) - at ) / 60 ))
    if   [ "$ago" -lt 60 ]   ; then ago="${ago}m ago"
    elif [ "$ago" -lt 2880 ] ; then ago="$(( ago / 60 ))h ago"
    else                            ago="$(( ago / 1440 ))d ago"; fi
  else
    ago="never"
  fi
  printf 'installed: %s\n' "$cur"
  printf 'latest: %s\n' "${latest:--}"
  printf 'state: %s\n' "${st:-unknown}"
  printf 'checked: %s\n' "$ago"
  printf 'mode: %s\n' "$MODE_SET"
  printf 'channel: %s\n' "$CHANNEL"
  printf 'lib: %s\n' "$LIB"
  [ -d "$PREV" ] && printf 'rollback: %s\n' "$(tr -d '[:space:]' < "$PREV/VERSION" 2>/dev/null || echo '?')"
  [ -n "$(state_get ERROR)" ] && printf 'error: %s\n' "$(state_get ERROR)"
  [ -n "$latest" ] && [ -s "$(notes_path "$latest")" ] && \
    printf 'headline: %s\n' "$(notes_headline "$latest")"
  return 0
}

case "$MODE" in
  check)    do_check ;;
  status)   do_status ;;
  notes)    do_notes "$NOTES_VER" ;;
  stage)    do_stage ;;
  apply)    do_apply ;;
  rollback) do_rollback ;;
  "")       sed -n '2,9p' "$0"; exit 0 ;;
esac
