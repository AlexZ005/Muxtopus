#!/usr/bin/env bash
# android-dev-setup.sh -- a user-local Android build toolchain on SteamOS (or any Linux).
#
#   android-dev-setup.sh                 install JDK 21 + Android SDK (platform 35, build-tools 35.0.0)
#   android-dev-setup.sh --with-emulator also the emulator and API 26 + API 21 x86_64 images (needs /dev/kvm)
#   android-dev-setup.sh --project DIR   additionally write DIR/local.properties (sdk.dir=...)
#   android-dev-setup.sh --udev          add the adb udev rule for the phone (asks for sudo)
#   android-dev-setup.sh --dev-keystore  create ~/.android/markor-fork.jks for signing release APKs (once)
#   android-dev-setup.sh --check         print what is installed and exit
#   android-dev-setup.sh --env           print the export lines and exit (for `eval "$(...)"`)
#
# WHY USER-LOCAL. SteamOS keeps / read-only and an OS update can wipe pacman
# packages, so everything here lands under $HOME: JDK in ~/.local/jdk, the SDK in
# ~/Android/Sdk, and one env file at ~/.config/android-dev.env that ~/.bashrc
# sources. Nothing needs root except the optional udev rule.
#
# IDEMPOTENT. Re-running verifies and fills gaps; downloads are checksummed and
# skipped when already present.
#
# Written 2026-09-13 for the Markor git-tab work; versions pinned below.
set -euo pipefail

# ------------------------------------------------------------------ pins
JDK_MAJOR=21
JDK_RELEASE="jdk-21.0.12.1+1"
JDK_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz"
JDK_SHA256="ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94"

CMDLINE_TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip"
CMDLINE_TOOLS_SHA256="4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"

ANDROID_PLATFORM="android-35"
ANDROID_BUILD_TOOLS="35.0.0"
EMULATOR_IMAGES=("system-images;android-26;google_apis;x86_64" "system-images;android-21;google_apis;x86_64")

# ----------------------------------------------------------------- paths
JDK_ROOT="$HOME/.local/jdk"
JDK_HOME="$JDK_ROOT/$JDK_RELEASE"
JDK_LINK="$JDK_ROOT/current"
SDK_ROOT="$HOME/Android/Sdk"
ENV_FILE="$HOME/.config/android-dev.env"
DL_DIR="$HOME/.cache/android-dev-setup"

WITH_EMULATOR=0; PROJECT_DIR=""; DO_UDEV=0; CHECK_ONLY=0; ENV_ONLY=0; DEV_KS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --with-emulator) WITH_EMULATOR=1; shift ;;
    --project) PROJECT_DIR="${2:?--project needs a directory}"; shift 2 ;;
    --udev) DO_UDEV=1; shift ;;
    --dev-keystore) DEV_KS=1; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    --env) ENV_ONLY=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

print_env() {
  cat <<EOF
export JAVA_HOME="$JDK_LINK"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="\$JAVA_HOME/bin:\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$ANDROID_HOME/emulator:\$PATH"
EOF
}

if [ "$ENV_ONLY" = 1 ]; then print_env; exit 0; fi

check() {
  echo "JDK:          $([ -x "$JDK_LINK/bin/java" ] && "$JDK_LINK/bin/java" -version 2>&1 | head -1 || echo missing)"
  echo "sdkmanager:   $([ -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ] && echo present || echo missing)"
  echo "platform:     $([ -d "$SDK_ROOT/platforms/$ANDROID_PLATFORM" ] && echo "$ANDROID_PLATFORM" || echo missing)"
  echo "build-tools:  $([ -d "$SDK_ROOT/build-tools/$ANDROID_BUILD_TOOLS" ] && echo "$ANDROID_BUILD_TOOLS" || echo missing)"
  echo "platform-tools: $([ -x "$SDK_ROOT/platform-tools/adb" ] && "$SDK_ROOT/platform-tools/adb" --version 2>/dev/null | head -1 || echo missing)"
  echo "emulator:     $([ -x "$SDK_ROOT/emulator/emulator" ] && echo present || echo missing)"
  echo "kvm:          $([ -e /dev/kvm ] && echo "/dev/kvm present" || echo "no /dev/kvm")"
  echo "env file:     $([ -f "$ENV_FILE" ] && echo "$ENV_FILE" || echo missing)"
}
if [ "$CHECK_ONLY" = 1 ]; then check; exit 0; fi

fetch() { # url sha256 dest
  local url="$1" sha="$2" dest="$3"
  if [ -f "$dest" ] && echo "$sha  $dest" | sha256sum -c --quiet - 2>/dev/null; then
    log "already downloaded: $(basename "$dest")"; return 0
  fi
  log "downloading $(basename "$dest")"
  curl -fL --retry 3 --progress-bar -o "$dest.part" "$url"
  echo "$sha  $dest.part" | sha256sum -c --quiet - || { echo "checksum mismatch for $url" >&2; rm -f "$dest.part"; exit 1; }
  mv "$dest.part" "$dest"
}

mkdir -p "$DL_DIR" "$JDK_ROOT" "$SDK_ROOT" "$(dirname "$ENV_FILE")"

# -------------------------------------------------------------------- JDK
if [ ! -x "$JDK_HOME/bin/java" ]; then
  fetch "$JDK_URL" "$JDK_SHA256" "$DL_DIR/temurin-$JDK_MAJOR.tar.gz"
  log "extracting JDK to $JDK_HOME"
  tmp="$(mktemp -d "$JDK_ROOT/.extract.XXXX")"
  tar -xzf "$DL_DIR/temurin-$JDK_MAJOR.tar.gz" -C "$tmp"
  mv "$tmp"/jdk-* "$JDK_HOME"
  rmdir "$tmp"
fi
ln -sfn "$JDK_HOME" "$JDK_LINK"
log "JDK: $("$JDK_LINK/bin/java" -version 2>&1 | head -1)"

# ------------------------------------------------------------- SDK tools
SDKM="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "$SDKM" ]; then
  fetch "$CMDLINE_TOOLS_URL" "$CMDLINE_TOOLS_SHA256" "$DL_DIR/commandlinetools-linux.zip"
  log "extracting command-line tools to $SDK_ROOT/cmdline-tools/latest"
  tmp="$(mktemp -d "$SDK_ROOT/.extract.XXXX")"
  unzip -q "$DL_DIR/commandlinetools-linux.zip" -d "$tmp"
  mkdir -p "$SDK_ROOT/cmdline-tools"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"
  mv "$tmp/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
  rmdir "$tmp"
fi

export JAVA_HOME="$JDK_LINK" ANDROID_HOME="$SDK_ROOT" ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$JAVA_HOME/bin:$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"

log "accepting SDK licenses"
yes | "$SDKM" --sdk_root="$SDK_ROOT" --licenses >/dev/null 2>&1 || true

PKGS=("platform-tools" "platforms;$ANDROID_PLATFORM" "build-tools;$ANDROID_BUILD_TOOLS")
if [ "$WITH_EMULATOR" = 1 ]; then
  if [ -e /dev/kvm ]; then
    PKGS+=("emulator" "${EMULATOR_IMAGES[@]}")
  else
    log "no /dev/kvm: the emulator would be unusably slow, skipping it"
  fi
fi
log "installing: ${PKGS[*]}"
"$SDKM" --sdk_root="$SDK_ROOT" --install "${PKGS[@]}" >/dev/null

if [ "$WITH_EMULATOR" = 1 ] && [ -e /dev/kvm ]; then
  AVDM="$SDK_ROOT/cmdline-tools/latest/bin/avdmanager"
  for img in "${EMULATOR_IMAGES[@]}"; do
    api="${img#system-images;android-}"; api="api${api%%;*}"
    if ! "$AVDM" list avd 2>/dev/null | grep -q "Name: $api\b"; then
      log "creating AVD $api"
      echo no | "$AVDM" create avd -n "$api" -k "$img" -d pixel >/dev/null
    fi
  done
  log "start one with:  emulator -avd api26 -no-snapshot -gpu swiftshader_indirect &"
fi

# -------------------------------------------------------------- env file
print_env > "$ENV_FILE"
if ! grep -qs "android-dev.env" "$HOME/.bashrc"; then
  printf '\n# Android build toolchain (android-dev-setup.sh)\n[ -f "%s" ] && . "%s"\n' "$ENV_FILE" "$ENV_FILE" >> "$HOME/.bashrc"
  log "added a source line to ~/.bashrc"
fi
log "env written to $ENV_FILE  (use now:  . $ENV_FILE)"

# ------------------------------------------------------- project wiring
if [ -n "$PROJECT_DIR" ]; then
  printf 'sdk.dir=%s\n' "$SDK_ROOT" > "$PROJECT_DIR/local.properties"
  log "wrote $PROJECT_DIR/local.properties"
fi

# ------------------------------------------------------------------ udev
if [ "$DO_UDEV" = 1 ]; then
  rule='SUBSYSTEM=="usb", ATTR{idVendor}=="22d9", MODE="0666", GROUP="plugdev", TAG+="uaccess"   # OPPO / OnePlus / realme'
  if [ ! -f /etc/udev/rules.d/51-android.rules ] || ! grep -q '22d9' /etc/udev/rules.d/51-android.rules; then
    log "writing /etc/udev/rules.d/51-android.rules (sudo)"
    echo "$rule" | sudo tee -a /etc/udev/rules.d/51-android.rules >/dev/null
    sudo udevadm control --reload-rules && sudo udevadm trigger
  fi
fi

# ---------------------------------------------------------- dev keystore
# A stable self-signed key so release (R8-minified) APKs built here install over
# each other on a phone. Password kept next to the env file, mode 600; this is a
# dev key for one person's device, not a store key.
if [ "$DEV_KS" = 1 ]; then
  KS="$HOME/.android/markor-fork.jks"; KS_ENV="$HOME/.config/android-dev-keystore.env"
  if [ ! -f "$KS" ]; then
    mkdir -p "$HOME/.android"
    pass="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
    umask 077; printf 'export MARKOR_KS="%s"\nexport MARKOR_KS_ALIAS="markor-fork"\nexport MARKOR_KS_PASS="%s"\n' "$KS" "$pass" > "$KS_ENV"; umask 022
    "$JDK_LINK/bin/keytool" -genkeypair -v -keystore "$KS" -alias markor-fork -keyalg RSA -keysize 4096 \
      -validity 10950 -storepass "$pass" -keypass "$pass" -dname "CN=Markor fork dev, OU=AlexZ005, O=AlexZ005" >/dev/null 2>&1
    log "created $KS (password in $KS_ENV)"
  else
    log "keystore already present: $KS"
  fi
  log "sign with:  . $KS_ENV && apksigner sign --ks \"\$MARKOR_KS\" --ks-key-alias \"\$MARKOR_KS_ALIAS\" --ks-pass env:MARKOR_KS_PASS --key-pass env:MARKOR_KS_PASS --out signed.apk unsigned.apk"
fi

echo
check
