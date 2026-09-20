#!/usr/bin/env bash
# test_update.sh -- the self-updater, end to end, against a release that does
# not exist on the internet.
#
#   bash tests/test_update.sh
#
# A SELF-UPDATER THAT HAS NEVER UPDATED ANYTHING is the one piece of this
# repository that cannot be proved by reading it: it replaces the code it is
# running from, and the interesting cases are the ones where that goes wrong.
# So this builds two releases from this checkout -- the one under test and a
# fabricated newer one -- serves them out of a directory with file:// URLs,
# installs the first, updates to the second and rolls back, in a scratch HOME
# that nothing outside is allowed to see.
#
# NO NETWORK, and that is checked rather than hoped for: MUXTOPUS_UPDATE_BASE,
# MUXTOPUS_UPDATE_TAG_URL and MUXTOPUS_TARBALL point at local files, and the
# one code path that would otherwise reach GitHub (the releases/latest
# redirect) is the one MUXTOPUS_UPDATE_TAG_URL replaces.
#
# NO_VENV is implied: every install here is --no-venv, because building it
# means a pip download and this test is about moving trees around.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
T="$(mktemp -d)"
trap 'rm -rf -- "${T:?}"' EXIT
fails=0
ok()   { echo "ok   $*"; }
bad()  { echo "FAIL $*"; fails=$((fails + 1)); }
is()   { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3: got '$1', want '$2'"; fi; }

V="$(tr -d '[:space:]' < "$ROOT/VERSION")"
# The fabricated newer release: this version with a major bump, so it sorts
# above anything the checkout could be and no real tag can collide with it.
V2="$(( ${V%%.*} + 1 )).0.0"

# ------------------------------------------------------- the two releases
# FROM THE WORKING TREE, not from HEAD: this is the test a person runs on the
# change they are about to commit, and a release built from HEAD would be a
# release without it in. release.sh only ever archives a REF, which is right
# for a release and wrong here, so the working tree becomes a commit in the
# throwaway clone first. (tests/test_release.sh is the one that proves HEAD.)
git clone -q --no-hardlinks "$ROOT" "$T/src" || { echo "cannot clone $ROOT"; exit 1; }
git -C "$T/src" config user.email t@example.invalid
git -C "$T/src" config user.name t
tar -cf - -C "$ROOT" --exclude=./.git --exclude=./.venv --exclude=./dist \
    --exclude=__pycache__ . | tar -xf - -C "$T/src" || { bad "could not copy the tree"; exit 1; }
git -C "$T/src" add -A
git -C "$T/src" commit -qm "the working tree" --allow-empty
(cd "$T/src" && ./release.sh build HEAD >/dev/null 2>&1) || { bad "release.sh build HEAD"; exit 1; }
mkdir -p "$T/rel/download/v$V"
cp "$T/src/dist/get.sh" "$T/src/dist/SHA256SUMS" "$T/src/dist/muxtopus-$V.tar.gz" "$T/rel/download/v$V/"

# The newer one is this commit with VERSION bumped: a real tarball, a real
# get.sh with a real sha256 in it, built by the real release.sh.
printf '%s\n' "$V2" > "$T/src/VERSION"
git -C "$T/src" commit -qam "v$V2"
(cd "$T/src" && ./release.sh build HEAD >/dev/null 2>&1) || { bad "release.sh build for $V2"; exit 1; }
mkdir -p "$T/rel/download/v$V2"
cp "$T/src/dist/get.sh" "$T/src/dist/SHA256SUMS" "$T/src/dist/muxtopus-$V2.tar.gz" "$T/rel/download/v$V2/"
printf 'v%s\n' "$V2" > "$T/rel/TAG"
ok "built $V and a fabricated $V2 from this commit"

# ------------------------------------------------------------ the install
H="$T/home"; mkdir -p "$H"
L="$H/.local/lib/muxtopus"
env -i PATH="/usr/local/bin:/usr/bin:/bin" HOME="$H" TERM=dumb \
  MUXTOPUS_TARBALL="file://$T/rel/download/v$V/muxtopus-$V.tar.gz" \
  bash "$T/rel/download/v$V/get.sh" --no-watchdog --no-venv > "$T/install.log" 2>&1
rc=$?
is "$rc" 0 "get.sh installs $V into the scratch HOME"
[ "$rc" = 0 ] || sed 's/^/    /' "$T/install.log"
is "$(tr -d '[:space:]' < "$L/VERSION" 2>/dev/null)" "$V" "the install is $V"

# Every call below is the installed tree's own updater, in that HOME, with
# every URL pointing into $T/rel.
up() {
  env -i PATH="/usr/local/bin:/usr/bin:/bin" HOME="$H" TERM=dumb \
    MUXTOPUS_UPDATE_BASE="file://$T/rel" \
    MUXTOPUS_UPDATE_TAG_URL="${TAG_URL:-file://$T/rel/TAG}" \
    MUXTOPUS_TARBALL="file://$T/rel/download/v$V2/muxtopus-$V2.tar.gz" \
    bash "$L/mux-update.sh" "$@"
}
STATE="$H/.local/state/muxtopus-update/state"

# ---------------------------------------------------------------- 1. check
up --check > "$T/check.log" 2>&1
is "$?" 0 "--check exits 0"
is "$(sed -n 's/^LATEST=//p' "$STATE" | tail -1)" "$V2" "the state file names $V2 as the newest"
is "$(sed -n 's/^STATE=//p' "$STATE" | tail -1)" "available" "and calls it available"
is "$(sed -n 's/^CURRENT=//p' "$STATE" | tail -1)" "$V" "and records what is installed"
up --status | grep -q "^latest: $V2" && ok "--status says so too" || bad "--status does not name $V2"
[ -d "$L.prev" ] && bad "nothing is installed yet but a .prev exists" || ok "a check installs nothing"

# THE SHARED CLOCK: a second check inside the interval must not ask anybody.
# Proved by pointing the tag URL at a file that does not exist -- if the
# check ran, it would fail and say so.
at="$(sed -n 's/^CHECKED_AT=//p' "$STATE" | tail -1)"
TAG_URL="file://$T/rel/NOPE" up --check >/dev/null 2>&1
is "$(sed -n 's/^CHECKED_AT=//p' "$STATE" | tail -1)" "$at" "a second check inside the interval asks nobody"
is "$(sed -n 's/^STATE=//p' "$STATE" | tail -1)" "available" "and keeps the answer it had"

# ...and --force goes anyway, which is what the dashboard's Check now row is.
TAG_URL="file://$T/rel/NOPE" up --check --force >/dev/null 2>&1
grep -q "^ERROR=could not reach" "$STATE" && ok "--force asks, and an unreachable repo is recorded" \
  || bad "--force did not ask, or did not record the failure"
is "$(sed -n 's/^LATEST=//p' "$STATE" | tail -1)" "$V2" "a failed check keeps the last good answer"
up --check --force >/dev/null 2>&1   # back to a good state for the rest

# ------------------------------------------------------------- 2. refusals
# A get.sh whose sha256 is not the one SHA256SUMS publishes must not run.
cp "$T/rel/download/v$V2/get.sh" "$T/good-get.sh"
printf '\n# tampered\n' >> "$T/rel/download/v$V2/get.sh"
up --apply --yes > "$T/tamper.log" 2>&1
[ "$?" = 0 ] && bad "a tampered get.sh was run" || ok "a tampered get.sh is refused"
grep -q "does not match its SHA256SUMS" "$T/tamper.log" && ok "and it says why" \
  || bad "no SHA256SUMS message: $(tail -1 "$T/tamper.log")"
is "$(tr -d '[:space:]' < "$L/VERSION")" "$V" "and nothing was installed"
cp "$T/good-get.sh" "$T/rel/download/v$V2/get.sh"

# A git checkout is never replaced by a tarball.
mkdir -p "$L/.git"
up --apply --yes > "$T/co.log" 2>&1
[ "$?" = 0 ] && bad "a git checkout was overwritten" || ok "a git checkout is refused"
grep -q "git.*pull" "$T/co.log" && ok "and it says to use git instead" || bad "no git pull message"
rmdir "$L/.git"

# Checks off means no request, whatever the clock says.
printf 'MUXTOPUS_UPDATE_MODE="off"\n' > "$H/.config/muxtopus/dashboard.conf"
rm -f "$STATE"
up --check >/dev/null 2>&1
is "$(sed -n 's/^STATE=//p' "$STATE" | tail -1)" "off" "MUXTOPUS_UPDATE_MODE=off makes no request"
rm -f "$H/.config/muxtopus/dashboard.conf"
up --check --force >/dev/null 2>&1

# ---------------------------------------------------------------- 3. apply
up --apply --yes > "$T/apply.log" 2>&1
is "$?" 0 "--apply --yes exits 0"
[ -s "$T/apply.log" ] || bad "--apply said nothing"
is "$(tr -d '[:space:]' < "$L/VERSION" 2>/dev/null)" "$V2" "$V2 is installed"
is "$(tr -d '[:space:]' < "$L.prev/VERSION" 2>/dev/null)" "$V" "and $V is kept as .prev"
is "$(env -i HOME="$H" PATH=/usr/bin:/bin bash "$H/.local/bin/muxtopus" --version)" "$V2" \
   "the muxtopus on PATH is $V2"
is "$(sed -n 's/^STATE=//p' "$STATE" | tail -1)" "applied" "the state file says applied"
ls -d "$H/.local/lib/muxtopus.old."* >/dev/null 2>&1 && bad "an .old tree was left behind" \
  || ok "no .old tree left behind"
# The install log is kept where the message says it is.
[ -f "$H/.local/state/muxtopus-update/install-$V2.log" ] && ok "the installer's output is kept" \
  || bad "no install-$V2.log"

# Applying again is refused: there is nothing newer.
up --apply --yes > "$T/again.log" 2>&1
[ "$?" = 0 ] && bad "--apply ran with nothing to do" || ok "--apply refuses when it is already the newest"

# ------------------------------------------------------------- 4. rollback
up --rollback --yes > "$T/back.log" 2>&1
is "$?" 0 "--rollback --yes exits 0"
is "$(tr -d '[:space:]' < "$L/VERSION" 2>/dev/null)" "$V" "$V is back in place"
is "$(tr -d '[:space:]' < "$L.prev/VERSION" 2>/dev/null)" "$V2" "and $V2 is now the tree to roll forward to"
is "$(env -i HOME="$H" PATH=/usr/bin:/bin bash "$H/.local/bin/muxtopus" --version)" "$V" \
   "the muxtopus on PATH is $V again"
# And forward again, out of the same pair: a rollback that cannot be undone
# is a trap rather than a safety net.
up --check --force >/dev/null 2>&1
up --apply --yes > "$T/fwd.log" 2>&1
is "$(tr -d '[:space:]' < "$L/VERSION" 2>/dev/null)" "$V2" "and it can be taken again afterwards"

# ------------------------------------------------------------ 5. the notes
printf 'notes for v%s\n' "$V2" > "$T/rel/notes"
MUXTOPUS_UPDATE_API="file://$T/rel/api" up --notes "$V2" > "$T/notes.log" 2>&1
grep -q "$V2" "$T/notes.log" && ok "--notes prints something naming the version" \
  || bad "--notes printed nothing useful"

[ "$fails" = 0 ] && echo "all passed" || echo "$fails failed"
exit $(( fails > 0 ))
