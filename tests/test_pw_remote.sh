#!/usr/bin/env bash
# The two halves of a remote e2e slot, without a browser: lib/pw-remote-shim.cjs
# (what launch() becomes) and lib/pw-remote-server.cjs (what it lets through).
#
#   bash tests/test_pw_remote.sh
#
# WHY FAKES. The real thing needs Playwright, a Chromium and, for the case
# that matters, a second machine. What can silently go wrong is narrower and
# is all here: the shim must hand the server the test's args but none of this
# machine's paths, expose the dev server's names, fall back to a local browser
# when the server does not answer, and leave persistent contexts local; the
# server must pick the backend by the client's version, strip what an --unsafe
# run-server would obey, and refuse a switch that starts a program. Both run
# with node; with no node the test says so and passes nothing.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
command -v node >/dev/null || { echo "SKIP: no node"; exit 0; }
T="$(mktemp -d "${TMPDIR:-/tmp}/mxpwr-XXXXXX")"
SRV_PID=""
trap '[ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; rm -rf "${T:?}"' EXIT
FAILS=0; PASSES=0
check() { local what="$1"; shift; if "$@"; then PASSES=$((PASSES+1)); echo "  ok   $what"; else FAILS=$((FAILS+1)); echo "  FAIL $what"; fi; }
has() { grep -qF -- "$2" "$1"; }

echo "== the shim: launch() becomes connect()"
# A fake `playwright` whose chromium records what it was asked.
mkdir -p "$T/app/node_modules/playwright"
cat > "$T/app/node_modules/playwright/index.js" <<'EOF'
const calls = [];
const fakeBrowser = (how) => ({ how, newContext: async () => ({ on() {}, pages: () => [] }), close: async () => {} });
const chromium = {
  calls,
  async launch(o) { calls.push(['launch', o]); return fakeBrowser('local'); },
  async launchPersistentContext(d, o) { calls.push(['persistent', d]); return { how: 'local-persistent' }; },
  async connect(ws, o) {
    calls.push(['connect', ws, o]);
    if (process.env.FAKE_CONNECT_FAILS) throw new Error('browserType.connect: WebSocket error: ' + ws + ' 503 Service Unavailable');
    return fakeBrowser('remote');
  }
};
module.exports = { chromium };
EOF
cat > "$T/app/t.cjs" <<'EOF'
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, args: ['--x'], executablePath: '/opt/chrome', env: { A: 1 }, logger: { isEnabled() {} } });
  const p = await chromium.launchPersistentContext('/tmp/prof', {});
  const h = await chromium.launch({ headless: false });
  console.log(JSON.stringify({ how: b.how, persistent: p.how, headed: h.how, calls: chromium.calls }));
})();
EOF
run_shim() { (cd "$T/app" && NODE_OPTIONS="--require \"$REPO/lib/pw-remote-shim.cjs\"" node t.cjs) > "$T/out" 2> "$T/err"; }
PW_REMOTE_WS=ws://pc:39001/ PW_REMOTE_EXPOSE= run_shim
c="$(node -e 'const r=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")); const c=r.calls.find(x=>x[0]==="connect"); console.log(JSON.stringify({how:r.how,ws:c&&c[1],lo:c&&JSON.parse(c[2].headers["x-playwright-launch-options"]),persistent:r.persistent,headed:r.headed}))' "$T/out")"
check "launch() connected to PW_REMOTE_WS" bash -c "[[ '$c' == *'\"how\":\"remote\",\"ws\":\"ws://pc:39001/\"'* ]]"
check "..with the test's args and headless" bash -c "[[ '$c' == *'\"lo\":{\"headless\":true,\"args\":[\"--x\"]}'* ]]"
check "..and none of executablePath, env or logger" bash -c "! [[ '$c' == *executablePath* || '$c' == *'\"env\"'* || '$c' == *logger* ]]"
check "..said so once on stderr" has "$T/err" "pw-remote-shim: chromium on ws://pc:39001/"
check "..and that executablePath was ignored" has "$T/err" "executablePath /opt/chrome ignored"
check "launchPersistentContext stays local, and says so" bash -c "[[ '$c' == *'\"persistent\":\"local-persistent\"'* ]] && grep -q 'launchPersistentContext runs on this machine' '$T/err'"
check "a headed launch stays local" bash -c "[[ '$c' == *'\"headed\":\"local\"'* ]]"

echo "== the shim: exposeNetwork"
PW_REMOTE_WS=ws://pc:39001/ run_shim
ex="$(node -e 'const r=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")); console.log(r.calls.find(x=>x[0]==="connect")[2].exposeNetwork)' "$T/out")"
check "<loopback> is always exposed" bash -c "[[ '$ex' == '<loopback>'* ]]"
loopnames="$(awk '!/^#/ && ($1 ~ /^127\./ || $1 == "::1") {for (i=2;i<=NF;i++) print tolower($i)}' /etc/hosts 2>/dev/null | head -1)"
if [ -n "$loopnames" ]; then
  check "..and the names /etc/hosts puts on loopback ($loopnames)" bash -c "[[ ',$ex,' == *',$loopnames,'* ]]"
fi
PW_REMOTE_WS=ws://pc:39001/ PW_REMOTE_EXPOSE='a.test,b.test' run_shim
check "PW_REMOTE_EXPOSE replaces the list" bash -c "grep -q '\"exposeNetwork\":\"a.test,b.test\"' '$T/out'"

echo "== the shim: a server that does not answer"
PW_REMOTE_WS=ws://pc:39001/ FAKE_CONNECT_FAILS=1 run_shim
check "falls back to a local launch" bash -c "grep -q '\"how\":\"local\"' '$T/out'"
check "..and says which server and why" has "$T/err" "remote browser at ws://pc:39001/ failed (browserType.connect: WebSocket error"
PW_REMOTE_WS=ws://pc:39001/ FAKE_CONNECT_FAILS=1 PW_REMOTE_FALLBACK=fail run_shim; rc=$?
check "PW_REMOTE_FALLBACK=fail makes it an error" [ "$rc" != 0 ]
(cd "$T/app" && NODE_OPTIONS="--require \"$REPO/lib/pw-remote-shim.cjs\"" node t.cjs) > "$T/out" 2> "$T/err"
check "no PW_REMOTE_WS: the shim does nothing" bash -c "grep -q '\"how\":\"local\"' '$T/out' && ! grep -q connect '$T/out' && [ ! -s '$T/err' ]"

echo "== the shim: PW_REMOTE_GPU=d3d11 on a Windows host"
# A launch with the Linux GPU flags a core suite passes, one with no GPU flag,
# and the args each connect sent.
cat > "$T/app/g.cjs" <<'EOF2'
const { chromium } = require('playwright');
(async () => {
  await chromium.launch({ args: ['--use-gl=angle', '--use-angle=vulkan', '--enable-features=Vulkan', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-unsafe-webgpu'] });
  await chromium.launch({ args: ['--use-angle=vulkan', '--enable-features=Vulkan,CanvasOopRasterization'] });
  await chromium.launch({ args: ['--no-sandbox', '--enable-features=Vulkan'] });
  await chromium.launch({ args: ['--use-angle=vulkan', '--disable-dawn-features=foo'] });
  const sent = chromium.calls.filter((x) => x[0] === 'connect').map((x) => JSON.parse(x[2].headers['x-playwright-launch-options']).args.join(' '));
  const local = chromium.calls.filter((x) => x[0] === 'launch').map((x) => x[1].args.join(' '));
  console.log(JSON.stringify({ sent, local }));
})();
EOF2
run_gpu() { (cd "$T/app" && NODE_OPTIONS="--require \"$REPO/lib/pw-remote-shim.cjs\"" node g.cjs) > "$T/out" 2> "$T/err"; }
nth() { node -e 'const r=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")); console.log(r[process.argv[2]][+process.argv[3]] ?? "")' "$T/out" "$1" "$2"; }
PW_REMOTE_WS=ws://pc:39001/ PW_REMOTE_GPU=d3d11 run_gpu
check "mapped: vulkan -> d3d11, the Vulkan feature dropped, every other arg kept" \
  [ "$(nth sent 0)" = "--use-gl=angle --use-angle=d3d11 --enable-gpu --ignore-gpu-blocklist --enable-unsafe-webgpu --disable-dawn-features=use_dxc" ]
check "..another feature in the list is kept" [ "$(nth sent 1)" = "--use-angle=d3d11 --enable-features=CanvasOopRasterization --disable-dawn-features=use_dxc" ]
check "..an existing --disable-dawn-features gains use_dxc" [ "$(nth sent 3)" = "--use-angle=d3d11 --disable-dawn-features=foo,use_dxc" ]
check "..a launch without --use-angle=vulkan is untouched" [ "$(nth sent 2)" = "--no-sandbox --enable-features=Vulkan" ]
check "..said once on stderr" bash -c "[ \"\$(grep -c 'pw-remote-shim: --use-angle=vulkan -> d3d11 on ws://pc:39001/' '$T/err')\" = 1 ]"
PW_REMOTE_WS=ws://pc:39001/ run_gpu
check "PW_REMOTE_GPU unset: the vulkan args go as they are" \
  [ "$(nth sent 0)" = "--use-gl=angle --use-angle=vulkan --enable-features=Vulkan --enable-gpu --ignore-gpu-blocklist --enable-unsafe-webgpu" ]
check "..and nothing is said about the GPU" bash -c "! grep -q 'use-angle' '$T/err'"
PW_REMOTE_WS=ws://pc:39001/ PW_REMOTE_GPU=keep run_gpu
check "PW_REMOTE_GPU=keep: unchanged too" [ "$(nth sent 1)" = "--use-angle=vulkan --enable-features=Vulkan,CanvasOopRasterization" ]
PW_REMOTE_WS=ws://pc:39001/ PW_REMOTE_GPU=d3d11 FAKE_CONNECT_FAILS=1 run_gpu
check "a local fallback keeps vulkan (this machine is not the Windows host)" \
  [ "$(nth local 0)" = "--use-gl=angle --use-angle=vulkan --enable-features=Vulkan --enable-gpu --ignore-gpu-blocklist --enable-unsafe-webgpu" ]

echo "== the server: one port, a backend per version"
# Fake installs: each cli.js is a tiny server that answers /json and, on an
# upgrade, sends back the request it got -- so the test sees what the router
# forwarded, header by header.
for v in 1.62.1 1.63.0; do
  mkdir -p "$T/root/playwright-$v/node_modules/playwright"
  cat > "$T/root/playwright-$v/node_modules/playwright/cli.js" <<EOF
const http = require('http');
const port = +process.argv[process.argv.indexOf('--port') + 1];
const s = http.createServer((q, r) => r.end('Running'));
s.on('upgrade', (q, sock) => {
  const body = JSON.stringify({ version: '$v', unsafe: process.argv.includes('--unsafe'), url: q.url, lo: q.headers['x-playwright-launch-options'] || null });
  sock.end('HTTP/1.1 200 OK\r\nContent-Length: ' + Buffer.byteLength(body) + '\r\n\r\n' + body);
});
s.listen(port, '127.0.0.1');
EOF
done
PORT=$(node -e 'const s=require("net").createServer().listen(0,"127.0.0.1",()=>{console.log(s.address().port);s.close()})')
node "$REPO/lib/pw-remote-server.cjs" --root "$T/root" --port "$PORT" --host 127.0.0.1 > "$T/srv.log" 2>&1 & SRV_PID=$!
for _ in $(seq 1 50); do (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break; sleep 0.1; done
cat > "$T/up.cjs" <<'EOF'
// An upgrade request as a Playwright client sends it; prints "<status> <body>".
const net = require('net');
const [port, ua, lo, path] = process.argv.slice(2);
const s = net.connect(+port, '127.0.0.1', () => {
  s.write(`GET ${path || '/'} HTTP/1.1\r\nHost: x\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n` +
    (ua ? `User-Agent: ${ua}\r\n` : '') + (lo ? `x-playwright-launch-options: ${lo}\r\n` : '') + '\r\n');
});
let buf = '';
s.on('data', (d) => (buf += d));
s.on('close', () => { const [head, body] = buf.split('\r\n\r\n'); console.log(head.split(' ')[1], (body || '').trim()); });
EOF
up() { node "$T/up.cjs" "$PORT" "$@"; }
j="$(bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT; printf 'GET /json HTTP/1.0\r\n\r\n' >&3; cat <&3" | tail -1)"
check "GET /json lists the installed versions" bash -c "[[ '$j' == *'\"versions\":[\"1.62.1\",\"1.63.0\"]'* ]]"
r="$(up 'Playwright/1.63.0 (x64; linux) node/24' '{"headless":true,"args":["--x"]}')"
check "a 1.63.0 client reaches the 1.63.0 backend, run --unsafe" bash -c "[[ '$r' == '200 '*'\"version\":\"1.63.0\",\"unsafe\":true'* ]]"
r="$(up 'Playwright/1.62.0 (x64; linux) node/24')"
check "a 1.62.0 client gets 1.62.1 (same major.minor)" bash -c "[[ '$r' == '200 '*'\"version\":\"1.62.1\"'* ]]"
r="$(up 'Playwright/1.64.2 (x64; linux) node/24')"
check "a version nobody installed: 503, saying what there is" bash -c "[[ '$r' == '503 playwright 1.64.x is not installed on this host (have: 1.62.1, 1.63.0)' ]]"
r="$(up '')"
check "no Playwright User-Agent: 400" bash -c "[[ '$r' == '400 '* ]]"

echo "== the server: what an --unsafe backend is never handed"
r="$(up 'Playwright/1.63.0' '{"headless":true,"executablePath":"C:\\x.exe","downloadsPath":"C:\\d","env":{"A":"1"},"args":["--use-gl=angle"]}')"
check "executablePath, downloadsPath and env are stripped; args kept" bash -c "[[ '$r' == '200 '* && '$r' != *executablePath* && '$r' != *downloadsPath* && '$r' != *'\\\"env'* && '$r' == *'--use-gl=angle'* ]]"
r="$(up 'Playwright/1.63.0' '{"args":["--renderer-cmd-prefix=calc.exe"]}')"
check "--renderer-cmd-prefix is refused (403)" bash -c "[[ '$r' == '403 the switch --renderer-cmd-prefix is not allowed'* ]]"
r="$(up 'Playwright/1.63.0' '{"args":["--gpu-launcher=x"]}')"
check "--gpu-launcher is refused (403)" bash -c "[[ '$r' == '403 '* ]]"
r="$(up 'Playwright/1.63.0' '' '/?launch-options=%7B%22executablePath%22%3A%22x%22%7D')"
check "launch options in the query string are cleaned too" bash -c "[[ '$r' == '200 '* && '$r' != *executablePath* && '$r' != *launch-options* ]]"
r="$(up 'Playwright/1.63.0' 'not json')"
check "launch options that are not JSON: 403" bash -c "[[ '$r' == '403 '* ]]"
check "the log names each refusal" bash -c "[ \"\$(grep -c 'refused 127.0.0.1' '$T/srv.log')\" -ge 5 ]"
GPU_LO='{"args":["--use-gl=angle","--use-angle=vulkan","--enable-features=Vulkan","--enable-unsafe-webgpu"]}'
r="$(up 'Playwright/1.63.0' "$GPU_LO")"
check "a Linux host keeps --use-angle=vulkan" bash -c '[[ "$1" == "200 "*"--use-angle=vulkan"*"--enable-features=Vulkan"* ]]' _ "$r"

echo "== the server on a Windows host: vulkan becomes d3d11"
kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
PW_REMOTE_PLATFORM=win32 node "$REPO/lib/pw-remote-server.cjs" --root "$T/root" --port "$PORT" --host 127.0.0.1 > "$T/srv.log" 2>&1 & SRV_PID=$!
for _ in $(seq 1 50); do (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break; sleep 0.1; done
r="$(up 'Playwright/1.63.0' "$GPU_LO")"
check "--use-angle=d3d11, no Vulkan feature, the other args kept" \
  bash -c '[[ "$1" == "200 "* && "$1" == *"--use-gl=angle"*"--use-angle=d3d11"*"--enable-unsafe-webgpu"* && "$1" == *"--disable-dawn-features=use_dxc"* && "$1" != *Vulkan* && "$1" != *vulkan* ]]' _ "$r"
r="$(up 'Playwright/1.63.0' '{"args":["--no-sandbox","--enable-features=Vulkan"]}')"
check "..a launch without --use-angle=vulkan is untouched" bash -c '[[ "$1" == "200 "*"--enable-features=Vulkan"* ]]' _ "$r"
r="$(up 'Playwright/1.63.0' '{"headless":true}')"
check "..and one with no args at all" bash -c '[[ "$1" == "200 "*"{\\\"headless\\\":true}"* ]]' _ "$r"

echo
if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed"; fi
[ "$FAILS" = 0 ]
