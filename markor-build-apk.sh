#!/usr/bin/env bash
# markor-build-apk.sh -- build and sign Markor fork APKs for a phone.
#
#   markor-build-apk.sh                 release APKs for flavorDefault (Markor) and flavorAtest (Marder, side-by-side)
#   markor-build-apk.sh --debug         also the flavorDefault debug APK
#   markor-build-apk.sh --repo DIR      checkout to build (default ~/.code/work/oss/markor)
#   markor-build-apk.sh --out DIR       where APKs land (default ~/.code/work/oss/markor-dist)
#
# Needs the toolchain from android-dev-setup.sh and the dev keystore from `android-dev-setup.sh --dev-keystore`.
# Release APKs are zipaligned and signed with that keystore (apksigner, v1+v2+v3), so successive builds
# install over each other. Output names carry the short commit sha.
set -euo pipefail
REPO="$HOME/.code/work/oss/markor"; OUT="$HOME/.code/work/oss/markor-dist"; DEBUG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --debug) DEBUG=1; shift ;;
    --repo) REPO="${2:?}"; shift 2 ;;
    --out) OUT="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
. "$HOME/.config/android-dev.env"
. "$HOME/.config/android-dev-keystore.env"
BT="$ANDROID_HOME/build-tools/35.0.0"
mkdir -p "$OUT"
cd "$REPO"
SHA="$(git rev-parse --short HEAD)"
log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }

sign() { # unsigned.apk out.apk
  "$BT/zipalign" -p -f 4 "$1" "$OUT/.aligned.apk"
  "$BT/apksigner" sign --ks "$MARKOR_KS" --ks-key-alias "$MARKOR_KS_ALIAS" \
    --ks-pass env:MARKOR_KS_PASS --key-pass env:MARKOR_KS_PASS --out "$2" "$OUT/.aligned.apk"
  rm -f "$OUT/.aligned.apk"
  "$BT/apksigner" verify "$2"
}

tasks=(assembleFlavorDefaultRelease assembleFlavorAtestRelease)
[ "$DEBUG" = 1 ] && tasks+=(assembleFlavorDefaultDebug)
rm -rf app/build/outputs/apk/flavorDefault app/build/outputs/apk/flavorAtest
log "building: ${tasks[*]} at $SHA"
./gradlew --console=plain -q "${tasks[@]}"

sign "$(ls app/build/outputs/apk/flavorDefault/release/*-release-unsigned.apk | head -1)" "$OUT/markor-git-tab-$SHA-release.apk"
sign "$(ls app/build/outputs/apk/flavorAtest/release/*-release-unsigned.apk | head -1)" "$OUT/marder-git-tab-$SHA-release.apk"
if [ "$DEBUG" = 1 ]; then
  cp "$(ls app/build/outputs/apk/flavorDefault/debug/*-debug.apk | head -1)" "$OUT/markor-git-tab-$SHA-debug.apk"
fi

echo
for f in "$OUT"/*-"$SHA"-*.apk; do
  printf '%-48s %8.1f MB  %s\n' "$(basename "$f")" "$(( $(stat -c %s "$f") / 104858 ))e-1" \
    "$("$BT/aapt" dump badging "$f" | grep -o "name='[^']*'\|sdkVersion:'[0-9]*'" | tr '\n' ' ')"
done
log "install: adb install -r <apk>   (or copy the file to the phone and open it)"
