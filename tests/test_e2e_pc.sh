#!/usr/bin/env bash
# e2e-slot's PC slots (MUXTOPUS_E2E_PC, lib/e2e-pc.sh, lib/e2e-pc-remote.sh):
# the letters and the order, --local and --exclusive, a dead host skipped, a
# run the host refuses going local, the environment that is and is not sent,
# the exit code, the lifeline, the dev server, the claim, the copy-back list,
# and the HOME rule.
#
#   bash tests/test_e2e_pc.sh
#
# THE FAR MACHINE IS THIS ONE. A fake `ssh` first on PATH runs the remote
# command here (and refuses for a host called "dead"), so rsync, the far half
# and lane-dev all run for real against the same filesystem. Same paths is the
# design (the far HOME must be ours), so the one thing this cannot show is a
# file arriving from elsewhere; the copy-back LIST is tested directly instead.
# The tree carries the mirror marker, or the far half would (rightly) refuse
# to sync over "a folder of its own".
#
# Private lock files, a scratch HOME and hosts.conf: nothing here can take a
# slot a real lane is waiting for or reach a real host.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
ES="$REPO/e2e-slot"
T="$(mktemp -d "${TMPDIR:-/tmp}/mxpc-XXXXXX")"
trap 'for p in $(cat "$T"/home/.local/state/lane-dev/*/pgid 2>/dev/null); do kill -- "-$p" 2>/dev/null; done; rm -rf "${T:?}"' EXIT
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_STATE_HOME="$T/home/.local/state" XDG_RUNTIME_DIR="$T/run"
export MUXTOPUS_CONFIG="$T/home/.config/muxtopus/config" E2E_SLOT_LOCK="$T/lock"
unset E2E_SLOTS E2E_REMOTE E2E_PREFER E2E_PC MUXTOPUS_E2E_SLOTS MUXTOPUS_E2E_REMOTE MUXTOPUS_E2E_PREFER MUXTOPUS_E2E_PC \
  NODE_OPTIONS MUXTOPUS_HOME MUXTOPUS_DIR CLAUDE_CONFIG_DIR MUXTOPUS_HOSTS APP_URL
mkdir -p "$HOME/.config/muxtopus" "$T/run" "$T/bin"
printf 'MUXTOPUS_E2E_SLOTS=2\nMUXTOPUS_E2E_PC=pc\n' > "$MUXTOPUS_CONFIG"
cat > "$HOME/.config/muxtopus/hosts.conf" <<'EOF'
# a test host: the fake ssh below runs everything here
[pc]
ssh = tester@pc.invalid   # comment after a value
e2e_slots = 2
gpu = cpu
[dead]
ssh = tester@dead.invalid
[otherhome]
ssh = tester@otherhome.invalid
EOF
# THE FAKE SSH: options dropped, -O check / -fN succeed, the rest is the
# remote command, run here by bash -- as sshd would, joined by spaces. stdin
# is passed through: it is the run's lifeline.
cat > "$T/bin/ssh" <<'EOF'
#!/usr/bin/env bash
target=""; check=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o|-p|-i|-l|-c|-m|-e) shift 2 ;;
    -O) check=1; shift 2 ;;
    -f|-N|-n|-T|-tt|-x|-q|-a|-A|-C) shift ;;
    -*) shift ;;
    *) target="$1"; shift; break ;;
  esac
done
case "$target" in *dead*) echo "ssh: connect to host dead: Connection refused" >&2; exit 255 ;; esac
[ "$check" = 1 ] && exit 0
[ $# = 0 ] && exit 0          # the -fN master
cd "$HOME" || exit 255        # sshd starts the command in HOME, with ITS environment
if [ "${target#*otherhome}" != "$target" ]; then exec env -i HOME=/nonexistent-home PATH="$PATH" bash -c "$*"; fi
exec env -i HOME="$HOME" PATH="$PATH" USER="${USER:-tester}" bash -c "$*"
EOF
chmod +x "$T/bin/ssh"
# A fake npm: `npm ci` makes a node_modules, `npm run dev -- --port P` serves HTTP.
cat > "$T/bin/npm" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  ci) mkdir -p node_modules/fake && echo "$(date +%s%N)" > node_modules/fake/installed; echo "npm-ci-ran" >&2 ;;
  run) shift; [ "$1" = dev ] || exit 1; while [ $# -gt 0 ] && [ "$1" != --port ]; do shift; done
       exec python3 -m http.server "$2" --bind 127.0.0.1 ;;
esac
EOF
chmod +x "$T/bin/npm"
export PATH="$T/bin:$PATH"
# node is required on the far side; a stub is enough when the real one is absent.
command -v node >/dev/null || { printf '#!/bin/sh\necho v0.0.0\n' > "$T/bin/node"; chmod +x "$T/bin/node"; }

TREE="$HOME/work/proj"
mkdir -p "$TREE/sub"
printf '{"name":"proj","scripts":{"dev":"vite dev"}}\n' > "$TREE/package.json"
: > "$TREE/.muxtopus-mirror"
FAILS=0; PASSES=0
check() { local what="$1"; shift; if "$@"; then PASSES=$((PASSES+1)); echo "  ok   $what"; else FAILS=$((FAILS+1)); echo "  FAIL $what"; fi; }
show='echo "$E2E_SLOT|${E2E_SLOT_PC:-}|${E2E_SLOT_REMOTE:-}|$LANG"'

echo "== a free pc slot is taken first: C, on pc"
cd "$TREE/sub" || exit 1
out="$("$ES" -- bash -c "$show" 2>"$T/err")"
check "slot C, E2E_SLOT_PC=pc, LANG=C.UTF-8 there" [ "$out" = "C|pc||C.UTF-8" ]
check "..the run said where it went" grep -q 'slot C is pc: the whole run is on pc' "$T/err"
check "..and how long each step took" grep -q 'pc run on pc: rc 0; mirror' "$T/err"
check "..its lock is .pc-pc-1" [ -f "$T/lock.pc-pc-1" ]
check "..two pc slots from e2e_slots = 2" [ -f "$T/lock.pc-pc-2" ]
check "--exclusive does not hold them, and is local" [ "$("$ES" --exclusive -- bash -c 'echo "$E2E_SLOT|${E2E_SLOT_PC:-}"' 2>/dev/null)" = "AB|" ]
check "--local never takes one" [ "$("$ES" --local -- bash -c "$show" 2>/dev/null)" = "A|||$LANG" ]
check "PREFER=local takes A while it is free" [ "$(E2E_PREFER=local "$ES" -- bash -c 'echo $E2E_SLOT' 2>/dev/null)" = A ]
check "E2E_PC= turns them off for one run" [ "$(E2E_PC= "$ES" -- bash -c 'echo $E2E_SLOT' 2>/dev/null)" = A ]
check "E2E_PC=pc:1 is one slot" [ "$(E2E_PC=pc:1 "$ES" -- bash -c 'echo $E2E_SLOT' 2>/dev/null)" = C ]
check "..and ':n' beats e2e_slots" [ ! -f "$T/lock.pc-pc-3" ]

echo "== the exit code, and the command as given"
"$ES" -- bash -c 'exit 7' 2>/dev/null; rc=$?
check "the command's exit code comes back (7)" [ "$rc" = 7 ]
"$ES" -- bash -c 'exit 76' 2>/dev/null; rc=$?
check "..a command's own 76 is not 'not here' (1, and not run twice)" [ "$rc" = 1 ]
out="$("$ES" -- printf '<%s>' 'a b' '$HOME' "it's" 2>/dev/null)"
check "arguments arrive unsplit and unexpanded" [ "$out" = "<a b><\$HOME><it's>" ]
check "..in the same folder" [ "$("$ES" -- pwd 2>/dev/null)" = "$TREE/sub" ]

echo "== the environment"
out="$(MY_VAR='x y' GH_TOKEN=s1 MY_API_KEY=s2 SOME_PASSWORD=s3 TMUX=t "$ES" -- bash -c 'echo "${MY_VAR:-}|${GH_TOKEN:-}|${MY_API_KEY:-}|${SOME_PASSWORD:-}|${TMUX:-}"' 2>/dev/null)"
check "a caller's variable goes; tokens, keys, passwords and TMUX do not" [ "$out" = "x y||||" ]
out="$(MY_API_KEY=s2 E2E_PC_ENV="MY_API_KEY" "$ES" -- bash -c 'echo "${MY_API_KEY:-}"' 2>/dev/null)"
check "..E2E_PC_ENV sends a name anyway" [ "$out" = s2 ]
out="$(NODE_OPTIONS=--foo "$ES" -- bash -c 'echo "${NODE_OPTIONS:-}"' 2>/dev/null)"
check "NODE_OPTIONS is not sent (it names files here)" [ -z "$out" ]

echo "== refusals: the run goes local"
mkdir -p "$HOME/work/mine/.git" && echo '{}' > "$HOME/work/mine/package.json" && echo x > "$HOME/work/mine/f"
cd "$HOME/work/mine" || exit 1
out="$("$ES" -- bash -c "$show" 2>"$T/err")"
check "a tree that is a checkout there (no marker): local A" [ "${out%%|*}" = A ]
check "..saying why" grep -q 'is a folder of this machine.s own' "$T/err"
cd "$TREE" || exit 1
out="$(E2E_PC=dead "$ES" -- bash -c "$show" 2>"$T/err")"
check "a dead host: local A" [ "${out%%|*}" = A ]
check "..said once" [ "$(grep -c 'pc host dead does not answer' "$T/err")" = 1 ]
out="$(E2E_PC=otherhome "$ES" -- bash -c "$show" 2>"$T/err")"
check "a host whose HOME differs: local A" [ "${out%%|*}" = A ]
out="$(E2E_PC=nosuch "$ES" -- bash -c "$show" 2>"$T/err")"
check "a name hosts.conf does not have: said, local A" bash -c "[ '${out%%|*}' = A ] && grep -q \"pc host 'nosuch' has no ssh\" '$T/err'"
cd / || exit 1
out="$("$ES" -- bash -c "$show" 2>"$T/err")"
check "a run outside HOME: local A" [ "${out%%|*}" = A ]
cd "$TREE" || exit 1

echo "== node_modules by lockfile, once per hash"
echo '{"lockfileVersion":3}' > "$TREE/package-lock.json"; mkdir -p "$TREE/node_modules"
"$ES" -- true 2>"$T/err"
check "a new lockfile: npm ci" grep -q 'npm-ci-ran' "$T/err"
"$ES" -- true 2>"$T/err"
check "..the same lockfile again: nothing" bash -c "! grep -q 'npm ci\\|npm-ci-ran\\|from the cache' '$T/err'"
rm -rf "${TREE:?}/node_modules"; mkdir -p "$TREE/node_modules"
"$ES" -- true 2>"$T/err"
check "..a tree without them, same hash: from the cache, no npm" bash -c "grep -q 'from the cache' '$T/err' && ! grep -q 'npm-ci-ran' '$T/err'"
check "..a hard-linked copy" [ -f "$TREE/node_modules/fake/installed" ]

echo "== E2E_PC_INPUTS: a repo only a sourced script names"
mkdir -p "$HOME/work/repos/modrepo/node_modules"; : > "$HOME/work/repos/modrepo/.muxtopus-mirror"
echo '{"lockfileVersion":3,"name":"modrepo"}' > "$HOME/work/repos/modrepo/package-lock.json"
E2E_PC_INPUTS="$HOME/work/repos/modrepo" "$ES" -- true 2>"$T/err"
check "its node_modules are built there too" grep -q "npm ci in $HOME/work/repos/modrepo" "$T/err"
"$ES" -- true 2>"$T/err"
check "..and not without it" bash -c "! grep -q 'modrepo' '$T/err'"

echo "== the dev server from APP_URL, on the same port"
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
out="$("$ES" -- env APP_URL="http://localhost:$PORT/" bash -c 'curl -s -o /dev/null -w "%{http_code}" "$APP_URL"' 2>"$T/err")"
check "APP_URL on localhost:$PORT: a server there, the test reaches it" [ "$out" = 200 ]
check "..left to lane-dev's idle timer" "$REPO/lane-dev" status "$PORT" --quiet
"$REPO/lane-dev" stop "$PORT" >/dev/null
out="$("$ES" --dev "$TREE" "$PORT" -- bash -c 'curl -s -o /dev/null -w "%{http_code}" "http://localhost:'"$PORT"'/"' 2>/dev/null)"
check "--dev: served there" [ "$out" = 200 ]
check "..and stopped after, as e2e-slot --dev does here" bash -c "! '$REPO/lane-dev' status $PORT --quiet"
out="$("$ES" -- env APP_URL="https://example.invalid:$PORT/" bash -c 'echo ok' 2>"$T/err")"
check "an APP_URL on another host starts nothing" bash -c "[ '$out' = ok ] && ! grep -q 'server :' '$T/err'"

echo "== the lifeline: the caller killed, the run stopped there"
"$ES" -- bash -c 'echo $$ > "$1"; sleep 60' _ "$T/far.pid" 2>/dev/null & EP=$!
for _ in $(seq 1 50); do [ -s "$T/far.pid" ] && break; sleep 0.1; done
kill -TERM "$EP"; wait "$EP" 2>/dev/null
gone=0; for _ in $(seq 1 100); do kill -0 "$(cat "$T/far.pid")" 2>/dev/null || { gone=1; break; }; sleep 0.1; done
check "the far command is gone within 10 s" [ "$gone" = 1 ]
check "..and its run folder" bash -c "[ -z \"\$(ls -A '$HOME/.cache/muxtopus-pc/runs' 2>/dev/null)\" ]"

echo "== the claim (the far half, directly)"
R="$HOME/.cache/muxtopus-pc/bin/e2e-pc-remote.sh"
mkdir -p "$HOME/repo/.git" "$HOME/empty"; echo x > "$HOME/repo/a"
out="$(bash "$R" claim "d:$HOME/repo" "d:$HOME/repo/sub" "d:$HOME/empty" "d:$HOME/new/dir" "f:$TREE/x.zip" "d:/etc")"
check "a checkout: no" grep -q "^no $HOME/repo " <<<"$out"
check "..inside one: no" grep -q "^no $HOME/repo/sub " <<<"$out"
check "an empty folder: ok" grep -qx "ok $HOME/empty" <<<"$out"
check "..and marked" [ -f "$HOME/empty/.muxtopus-mirror" ]
check "a new folder: ok" grep -qx "ok $HOME/new/dir" <<<"$out"
check "..and made" [ -d "$HOME/new/dir" ]
check "a file inside a mirror: ok" grep -q "^ok $TREE/x.zip$" <<<"$out"
check "outside HOME and /tmp: no" grep -q "^no /etc " <<<"$out"

echo "== the copy-back list (the far half, directly)"
echo 'export X=1' | bash "$R" envin t1; sleep 1.1
mkdir -p "$TREE/out" "$TREE/node_modules/z" "$HOME/ev"
echo a > "$TREE/out/shot.png"; echo b > "$TREE/node_modules/z/new"; echo c > "$HOME/ev/e.txt"
TF="$(mktemp /tmp/mxpc-back-XXXXXX)"; echo d > "$TF"
list="$(bash "$R" back t1 "$TREE" "$HOME/ev" | tr '\0' '\n')"
check "a new file in the tree" grep -qx "$TREE/out/shot.png" <<<"$list"
check "..not one in node_modules" bash -c "! grep -q node_modules <<<'$list'"
check "a named evidence folder" grep -qx "$HOME/ev/e.txt" <<<"$list"
check "a new file in /tmp" grep -qx "$TF" <<<"$list"
check "..not an old one" bash -c "! grep -qx '$TREE/package.json' <<<'$list'"
rm -f "$TF"; bash "$R" clean t1

echo
if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed"; fi
[ "$FAILS" = 0 ]
