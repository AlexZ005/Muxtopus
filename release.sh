#!/usr/bin/env bash
# release.sh -- build what a GitHub release of muxtopus carries.
#
#   release.sh notes [X.Y.Z]   print that version's CHANGELOG entry (default: VERSION)
#   release.sh build [REF]     dist/: muxtopus-X.Y.Z.tar.gz, get.sh, SHA256SUMS
#                              REF defaults to vX.Y.Z; HEAD makes a trial build
#
# The whole procedure, fragments to published release, is docs/releasing.md.
#
# THE TARBALL IS THE TAG, byte for byte: `git archive` of REF, so nothing from
# the working tree -- no .venv, no scratch file, no uncommitted edit -- can
# ride along. It is reproducible, too (git archive stamps the commit's time,
# gzip -n drops its own), so building it twice gives the same sha256, and
# the sum baked into get.sh can be checked by anybody who builds it again.
#
# THE VERSION IS READ FROM REF's OWN VERSION FILE, not the working tree's, and
# a vX.Y.Z tag whose VERSION says anything else is refused: the tag, the
# tarball's name, get.sh and the dashboard's header all say one number.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

die() { echo "release.sh: $*" >&2; exit 1; }

notes() {
  local v="${1:-$(cat VERSION)}"
  [ -f CHANGELOG.md ] || die "no CHANGELOG.md"
  # From "## v<v>" up to the next "## v" heading, leading blank lines dropped.
  local body
  body="$(awk -v v="$v" '
    /^## v[0-9]/ { if (on) exit; if ($2 == "v" v) { on = 1; next } }
    on' CHANGELOG.md | sed -e '/./,$!d')"
  [ -n "$body" ] || die "CHANGELOG.md has no '## v$v' entry"
  printf '%s\n' "$body"
}

build() {
  local v ref="${1:-}" name out sha
  if [ -z "$ref" ]; then ref="v$(cat VERSION)"; fi
  git rev-parse --verify --quiet "$ref^{commit}" >/dev/null || die "no such ref: $ref"
  v="$(git show "$ref:VERSION" | tr -d '[:space:]')"
  case "$ref" in
    v[0-9]*) [ "$ref" = "v$v" ] || die "$ref's VERSION file says $v" ;;
  esac
  name="muxtopus-$v"
  out="$ROOT/dist"
  rm -rf -- "${out:?}"
  mkdir -p "$out"

  git archive --format=tar --prefix="$name/" "$ref" | gzip -n -9 > "$out/$name.tar.gz"
  sha="$(sha256sum "$out/$name.tar.gz" | cut -d' ' -f1)"
  git show "$ref:packaging/get.sh.in" \
    | sed -e "s/@VERSION@/$v/g" -e "s/@SHA256@/$sha/g" > "$out/get.sh"
  chmod +x "$out/get.sh"
  grep -q '@[A-Z0-9]*@' "$out/get.sh" && die "get.sh still has a placeholder in it"
  (cd "$out" && sha256sum "$name.tar.gz" get.sh > SHA256SUMS)

  echo "built $ref ($(git rev-parse --short "$ref^{commit}")) as $v:"
  (cd "$out" && ls -l "$name.tar.gz" get.sh SHA256SUMS && cat SHA256SUMS)
}

case "${1:-}" in
  notes) shift; notes "$@" ;;
  build) shift; build "$@" ;;
  -h|--help|"") sed -n '2,7p' "$0" ;;
  *) die "unknown command: $1 (notes | build)" ;;
esac
