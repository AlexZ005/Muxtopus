#!/usr/bin/env bash
# test_release.sh -- build a release from HEAD and install it with its get.sh,
# into a scratch HOME. An installer nobody has run is a bug with a version
# number, so CI runs this one on every pull request.
#
#   bash tests/test_release.sh            (NO_VENV=1 skips the pip download)
#
# Nothing outside the scratch directory is touched: HOME, XDG_* and the
# install prefix all point into it, the watchdog is skipped, and release.sh
# writes only dist/ -- into a scratch clone, not this checkout.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
T="$(mktemp -d)"
trap 'rm -rf -- "${T:?}"' EXIT
fails=0
ok()   { echo "ok   $*"; }
bad()  { echo "FAIL $*"; fails=$((fails + 1)); }
is()   { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3: got '$1', want '$2'"; fi; }

V="$(tr -d '[:space:]' < "$ROOT/VERSION")"

# A clone of HEAD, so dist/ is not written into the checkout under test.
git clone -q --no-hardlinks "$ROOT" "$T/src" || { echo "cannot clone $ROOT"; exit 1; }
git -C "$T/src" checkout -q "$(git -C "$ROOT" rev-parse HEAD)"
(cd "$T/src" && ./release.sh build HEAD >/dev/null) || { bad "release.sh build HEAD"; exit 1; }
D="$T/src/dist"

[ -f "$D/muxtopus-$V.tar.gz" ] && ok "the tarball is named for VERSION ($V)" || bad "no muxtopus-$V.tar.gz"
grep -q '@[A-Z0-9]*@' "$D/get.sh" && bad "get.sh still has a placeholder" || ok "get.sh is fully stamped"
sha="$(sha256sum "$D/muxtopus-$V.tar.gz" | cut -d' ' -f1)"
grep -q "sha=\"$sha\"" "$D/get.sh" && ok "get.sh carries the tarball's sha256" || bad "get.sh's sha256 is not the tarball's"
grep -q "version=\"$V\"" "$D/get.sh" && ok "get.sh carries VERSION" || bad "get.sh's version is not $V"
(cd "$D" && sha256sum -c --quiet SHA256SUMS) && ok "SHA256SUMS verifies" || bad "SHA256SUMS does not verify"
tar -tzf "$D/muxtopus-$V.tar.gz" | grep -qv "^muxtopus-$V/" && bad "a tarball entry outside muxtopus-$V/" \
  || ok "every tarball entry is under muxtopus-$V/"
tar -tzf "$D/muxtopus-$V.tar.gz" | grep -q '\.venv\|__pycache__\|^muxtopus-[^/]*/dist/' \
  && bad "the tarball carries a venv, bytecode or dist/" || ok "the tarball is the commit and nothing else"

# Reproducible: a second build is the same bytes.
cp "$D/muxtopus-$V.tar.gz" "$T/first.tar.gz"
(cd "$T/src" && ./release.sh build HEAD >/dev/null)
cmp -s "$T/first.tar.gz" "$D/muxtopus-$V.tar.gz" && ok "building twice gives the same tarball" \
  || bad "the tarball is not reproducible"

# notes: the entry for VERSION, without its own heading.
if [ -f "$ROOT/CHANGELOG.md" ]; then
  n="$(cd "$T/src" && ./release.sh notes)"
  [ -n "$n" ] && ok "release.sh notes prints the v$V entry" || bad "release.sh notes is empty"
  printf '%s\n' "$n" | grep -q "^## v" && bad "notes run into another version's entry" \
    || ok "notes stop at the next version"
fi

# Install it, as somebody who has never had it.
H="$T/home"; mkdir -p "$H"
run_get() {
  env -i PATH="$H/.local/bin:/usr/local/bin:/usr/bin:/bin" HOME="$H" TERM=dumb \
    MUXTOPUS_TARBALL="${TB:-file://$D/muxtopus-$V.tar.gz}" ${LIB:+MUXTOPUS_LIB=$LIB} \
    bash "$D/get.sh" --no-watchdog ${NO_VENV:+--no-venv} "$@"
}
run_get > "$T/get.log" 2>&1; rc=$?
is "$rc" 0 "get.sh exits 0 on a fresh HOME"
[ "$rc" = 0 ] || sed 's/^/    /' "$T/get.log"
L="$H/.local/lib/muxtopus"
is "$(readlink "$H/.local/bin/muxtopus")" "$L/muxtopus" "the muxtopus link points into ~/.local/lib/muxtopus"
is "$(env -i HOME="$H" PATH=/usr/bin:/bin bash "$H/.local/bin/muxtopus" --version)" "$V" "the installed muxtopus --version is $V"
is "$(cat "$L/.muxtopus-release" 2>/dev/null)" "$V" "the install is marked as get.sh's"
grep -q "^MUXTOPUS_DIR=\"$L\"" "$H/.config/muxtopus/config" && ok "the config pins MUXTOPUS_DIR to it" \
  || bad "the config does not pin MUXTOPUS_DIR=$L"
[ -d "$H/.local/share/muxtopus/schedules" ] && ok "the data folders are seeded" || bad "no schedules/ under the data home"
if [ -z "${NO_VENV:-}" ]; then
  "$L/.venv/bin/python" -c 'import rich' 2>/dev/null && ok "the dashboard venv has rich" || bad "no rich in $L/.venv"
fi

# Again: an upgrade in place keeps the venv and the config.
echo "# mine" >> "$H/.config/muxtopus/config"
touch "$L/.venv/keep-me" 2>/dev/null
run_get > "$T/get2.log" 2>&1; rc=$?
is "$rc" 0 "a second get.sh (upgrade in place) exits 0"
grep -q "^# mine" "$H/.config/muxtopus/config" && ok "the upgrade leaves the config alone" || bad "the upgrade rewrote the config"
if [ -z "${NO_VENV:-}" ]; then
  [ -e "$L/.venv/keep-me" ] && ok "the upgrade carries the venv across" || bad "the upgrade lost the venv"
fi
ls -d "$H/.local/lib/muxtopus.old."* >/dev/null 2>&1 && bad "an old tree was left behind" || ok "no old tree left behind"
# THE ONE TREE THAT IS KEPT, and only one: the release being replaced becomes
# muxtopus.prev, which is what `muxtopus update --rollback` puts back.
is "$(cat "$H/.local/lib/muxtopus.prev/VERSION" 2>/dev/null | tr -d '[:space:]')" "$V" \
   "the replaced tree is kept as muxtopus.prev"
ls -d "$H/.local/lib/muxtopus.prev.old."* >/dev/null 2>&1 && bad "a second generation was kept" \
  || ok "only one generation is kept"

# What it must refuse.
cp "$D/muxtopus-$V.tar.gz" "$T/bad.tar.gz"; printf x >> "$T/bad.tar.gz"
TB="file://$T/bad.tar.gz" LIB="$T/other" run_get > "$T/bad.log" 2>&1 \
  && bad "a corrupted tarball was installed" || ok "a corrupted tarball is refused"
grep -q "checksum mismatch" "$T/bad.log" && ok "and it says why" || bad "no checksum message"
[ -e "$T/other" ] && bad "the refused install left $T/other" || ok "and nothing was unpacked"
mkdir -p "$T/co/.git"
LIB="$T/co" run_get > "$T/co.log" 2>&1 && bad "get.sh installed over a git checkout" \
  || ok "get.sh refuses to replace a git checkout"
mkdir -p "$T/theirs"; echo x > "$T/theirs/file"
LIB="$T/theirs" run_get > "$T/theirs.log" 2>&1 && bad "get.sh installed over a directory it did not make" \
  || ok "get.sh refuses a non-empty directory it did not make"

[ "$fails" = 0 ] && echo "all passed" || echo "$fails failed"
exit $(( fails > 0 ))
