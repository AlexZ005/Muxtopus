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
