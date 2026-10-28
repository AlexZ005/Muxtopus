#!/usr/bin/env bash
# e2e-slot's slot COUNT: MUXTOPUS_E2E_SLOTS (or E2E_SLOTS for one run), and
# its REMOTE slots: MUXTOPUS_E2E_REMOTE, the health check, MUXTOPUS_E2E_PREFER,
# --local, and --exclusive holding them too.
#
#   bash tests/test_e2e_slots.sh
#
# WHY. Two slots were right for the box e2e-slot was written on and wrong for
# a bigger one, and a budget that lets twelve lanes run queued most of them
# here. The count is a knob now; these cases hold what it must not break: the
# two-slot files are still slot A and B (an old e2e-slot and a new one share
# them), --exclusive holds every slot, and a full house still exits 75.
#
# Private lock files (E2E_SLOT_LOCK) and a scratch HOME: nothing here can
# take a slot a real lane is waiting for.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
ES="$REPO/e2e-slot"
T="$(mktemp -d "${TMPDIR:-/tmp}/mxslots-XXXXXX")"
HEALTH_PID=""
trap '[ -n "$HEALTH_PID" ] && kill "$HEALTH_PID" 2>/dev/null; rm -rf "${T:?}"' EXIT
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" MUXTOPUS_CONFIG="$T/home/.config/muxtopus/config"
unset E2E_SLOTS E2E_REMOTE E2E_PREFER E2E_REMOTE_GPU PW_REMOTE_GPU MUXTOPUS_E2E_SLOTS MUXTOPUS_E2E_REMOTE MUXTOPUS_E2E_PREFER MUXTOPUS_E2E_REMOTE_GPU NODE_OPTIONS MUXTOPUS_HOME MUXTOPUS_DIR CLAUDE_CONFIG_DIR
mkdir -p "$HOME/.config/muxtopus"; : > "$MUXTOPUS_CONFIG"
export E2E_SLOT_LOCK="$T/lock"
FAILS=0; PASSES=0
check() { local what="$1"; shift; if "$@"; then PASSES=$((PASSES+1)); echo "  ok   $what"; else FAILS=$((FAILS+1)); echo "  FAIL $what"; fi; }

# hold N: N runs that each take a slot and sit on it; their letters in $T/got
# (local slots first, so a remote slot configured below stays free, and their
# pids kept: a plain `wait` would also wait for the stand-in health server)
HOLDS=()
hold() { local i; : > "$T/got"; HOLDS=()
  for i in $(seq 1 "$1"); do E2E_PREFER=local "$ES" -- bash -c 'echo "$E2E_SLOT" >> "$1"; sleep 4' _ "$T/got" & HOLDS+=($!); done
  sleep 1.5; }
unhold() { wait "${HOLDS[@]}"; }

echo "== --help prints the header, and takes no slot"
out="$("$ES" --help 2>&1)"; rc=$?
check "--help exits 0 with the usage line" bash -c '[ "$1" = 0 ] && grep -q "e2e-slot \[--exclusive\]" <<<"$2"' _ "$rc" "$out"
check "..and ran nothing (no lock file made)" [ ! -e "$T/lock" ]

echo "== the default is two: A and B, and a third waits"
hold 2
check "two runs got A and B" [ "$(sort "$T/got" | paste -sd, -)" = "A,B" ]
"$ES" --wait 1 -- true; rc=$?
check "a third, with both held, exits 75" [ "$rc" = 75 ]
check "..and the two locks are the classic files" bash -c "[ -f '$T/lock' ] && [ -f '$T/lock.b' ] && [ ! -e '$T/lock.c' ]"
wait

echo "== MUXTOPUS_E2E_SLOTS=3 in the config: three at once"
printf 'MUXTOPUS_E2E_SLOTS=3\n' > "$MUXTOPUS_CONFIG"
hold 3
check "three runs got A, B and C" [ "$(sort "$T/got" | paste -sd, -)" = "A,B,C" ]
check "..C's lock is .c" [ -f "$T/lock.c" ]
wait
check "--exclusive holds every slot" [ "$("$ES" --exclusive -- bash -c 'echo $E2E_SLOT')" = ABC ]

echo "== E2E_SLOTS in the environment beats the config for one run"
hold 1
E2E_SLOTS=1 "$ES" --wait 1 -- true; rc=$?
check "E2E_SLOTS=1 with A held: 75" [ "$rc" = 75 ]
wait
check "nonsense in the config is the old two" bash -c "printf 'MUXTOPUS_E2E_SLOTS=lots\n' > '$MUXTOPUS_CONFIG'; [ \"\$('$ES' --exclusive -- bash -c 'echo \$E2E_SLOT')\" = AB ]"

echo "== remote slots: a host that answers GET /json"
# A stand-in for pw-remote-server: any HTTP server with a /json is "up".
mkdir -p "$T/www"; echo '{"ok":true}' > "$T/www/json"
HPORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
python3 -m http.server "$HPORT" --bind 127.0.0.1 --directory "$T/www" >/dev/null 2>&1 & HEALTH_PID=$!
for _ in $(seq 1 50); do (exec 3<>"/dev/tcp/127.0.0.1/$HPORT") 2>/dev/null && break; sleep 0.1; done
DEAD=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
printf 'MUXTOPUS_E2E_SLOTS=2\nMUXTOPUS_E2E_REMOTE=127.0.0.1:%s\n' "$HPORT" > "$MUXTOPUS_CONFIG"
show='echo "$E2E_SLOT|$E2E_SLOT_REMOTE|$PW_REMOTE_WS|$NODE_OPTIONS"'
out="$("$ES" -- bash -c "$show" 2>/dev/null)"
check "a free remote slot is preferred: slot C, remote" [ "${out%%|*}" = C ]
check "..the command sees E2E_SLOT_REMOTE and PW_REMOTE_WS" [ "$(cut -d'|' -f2,3 <<<"$out")" = "127.0.0.1:$HPORT|ws://127.0.0.1:$HPORT/" ]
check "..and the shim in NODE_OPTIONS" bash -c "[[ '$(cut -d'|' -f4 <<<"$out")' == *'--require \"$REPO/lib/pw-remote-shim.cjs\"'* ]]"
check "..its lock is .remote1, not a letter" [ -f "$T/lock.remote1" ]
out="$(NODE_OPTIONS=--max-old-space-size=512 "$ES" -- bash -c 'echo "$NODE_OPTIONS"' 2>/dev/null)"
check "..a caller's NODE_OPTIONS is kept" bash -c "[[ '$out' == '--max-old-space-size=512 --require '* ]]"
out="$("$ES" --local -- bash -c "$show" 2>/dev/null)"
check "--local takes a local slot, no shim" [ "$out" = "A|||" ]
out="$(E2E_PREFER=local "$ES" -- bash -c "$show" 2>/dev/null)"
check "PREFER=local takes A while it is free" [ "${out%%|*}" = A ]
hold 2
out="$(E2E_PREFER=local "$ES" --wait 6 -- bash -c "$show" 2>/dev/null)"
check "..and the remote slot once A and B are held" [ "${out%%|*}" = C ]
E2E_PREFER=local "$ES" --local --wait 1 -- true; rc=$?
check "--local with A and B held: 75, never the remote slot" [ "$rc" = 75 ]
unhold
check "--exclusive holds the remote slot too, and is local" [ "$("$ES" --exclusive -- bash -c 'echo "$E2E_SLOT|$E2E_SLOT_REMOTE"')" = "ABC|" ]
check "E2E_REMOTE= turns them off for one run" [ "$(E2E_REMOTE= "$ES" --exclusive -- bash -c 'echo $E2E_SLOT')" = AB ]
check "the same host twice is two slots" [ "$(E2E_REMOTE="127.0.0.1:$HPORT,127.0.0.1:$HPORT" "$ES" --exclusive -- bash -c 'echo $E2E_SLOT')" = ABCD ]

echo "== remote slots: MUXTOPUS_E2E_REMOTE_GPU reaches the command as PW_REMOTE_GPU"
gshow='echo "$E2E_SLOT|${PW_REMOTE_GPU-unset}"'
check "unset: no PW_REMOTE_GPU" [ "$("$ES" -- bash -c "$gshow" 2>/dev/null)" = "C|unset" ]
check "..and a caller's stray PW_REMOTE_GPU is not passed on" [ "$(PW_REMOTE_GPU=d3d11 "$ES" -- bash -c "$gshow" 2>/dev/null)" = "C|unset" ]
printf 'MUXTOPUS_E2E_SLOTS=2\nMUXTOPUS_E2E_REMOTE=127.0.0.1:%s\nMUXTOPUS_E2E_REMOTE_GPU=d3d11\n' "$HPORT" > "$MUXTOPUS_CONFIG"
check "d3d11 in the config: the remote run sees PW_REMOTE_GPU=d3d11" [ "$("$ES" -- bash -c "$gshow" 2>/dev/null)" = "C|d3d11" ]
check "..a local run does not" [ "$("$ES" --local -- bash -c "$gshow" 2>/dev/null)" = "A|unset" ]
check "E2E_REMOTE_GPU=keep beats it for one run" [ "$(E2E_REMOTE_GPU=keep "$ES" -- bash -c "$gshow" 2>/dev/null)" = "C|unset" ]
printf 'MUXTOPUS_E2E_SLOTS=2\nMUXTOPUS_E2E_REMOTE=127.0.0.1:%s\n' "$HPORT" > "$MUXTOPUS_CONFIG"
check "E2E_REMOTE_GPU=d3d11 for one run" [ "$(E2E_REMOTE_GPU=d3d11 "$ES" -- bash -c "$gshow" 2>/dev/null)" = "C|d3d11" ]
err="$(E2E_REMOTE_GPU=metal "$ES" -- bash -c "$gshow" 2>&1)"
check "a value it does not know is said and treated as keep" bash -c 'grep -q "ignoring remote GPU setting .metal." <<<"$1" && grep -q "^C|unset$" <<<"$1"' _ "$err"

echo "== a remote host that does not answer is skipped"
out="$(E2E_REMOTE="127.0.0.1:$DEAD" "$ES" -- bash -c "$show" 2>/dev/null)"
check "a dead host: the run takes local A" [ "$out" = "A|||" ]
out="$(E2E_REMOTE="127.0.0.1:$DEAD,127.0.0.1:$HPORT" "$ES" -- bash -c "$show" 2>/dev/null)"
check "dead first, live second: the live one (D)" [ "${out%%|*}" = D ]
err="$(E2E_REMOTE="nonsense,host:12x" "$ES" -- true 2>&1 >/dev/null)"
check "a malformed entry is said and ignored" bash -c "[ \"\$(grep -c 'ignoring remote slot' <<<'$err')\" = 2 ]"

echo
if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed"; fi
[ "$FAILS" = 0 ]
