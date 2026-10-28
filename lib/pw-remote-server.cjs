#!/usr/bin/env node
'use strict';
// pw-remote-server.cjs -- the far end of e2e-slot's remote slots: one port that
// serves every Playwright version the lanes use.
//
//   node pw-remote-server.cjs --root DIR [--port 39001] [--host 0.0.0.0]
//                             [--allow 198.51.100.7[,...]] [--install]
//
// Runs on the machine that lends its browser (Windows or Linux; Node only, no
// packages). DIR holds one folder per Playwright version, each self-contained,
// so a version is removed by deleting its folder:
//   DIR/playwright-1.62.1/node_modules/playwright   (npm install --prefix ... playwright@1.62.1)
//   DIR/playwright-1.62.1/browsers/                 (its PLAYWRIGHT_BROWSERS_PATH, when it exists)
//
// WHY A ROUTER AND NOT `playwright run-server`. Two things run-server cannot do:
//
// 1. VERSIONS. A client refuses a server whose major.minor is not its own (HTTP
//    428, "Playwright version mismatch"), and on the day this was written the
//    Deck's lanes used 1.62.1 and 1.63.0 side by side. One run-server per version
//    on a port of its own would make every lane's slot depend on its lockfile.
//    Here the client's User-Agent ("Playwright/1.63.0 ...") picks the backend: a
//    run-server for that version, started on first use on 127.0.0.1 and kept.
//
// 2. ARGS. run-server drops a client's `args` unless it runs with --unsafe
//    (filterLaunchOptions), and every core suite passes args (the no-throttle
//    flags; GPU_ARGS for the frame-rate suites) -- without them the results are
//    not the Deck's results. But --unsafe also accepts `executablePath`, which on
//    an unauthenticated port is "run any program on this PC". So the backends run
//    --unsafe on loopback only, and this router rewrites every client's launch
//    options first: no executablePath, no paths on this disk, and no Chromium
//    switch that starts a program (--renderer-cmd-prefix, --gpu-launcher, ...).
//    A request carrying one is refused (403) rather than quietly edited, so a
//    test that needed it fails loudly instead of measuring something else.
//
// THE PORT IS STILL UNAUTHENTICATED: anyone who reaches it gets a browser on
// this machine, inside your network. --allow (default: loopback only) is the
// second fence; the first is a firewall rule that admits only the test machine.
//
// --install: a version nobody installed yet is installed on its first request
// (npm, then `playwright install chromium`). That first request is refused with
// 503 while it runs -- an install takes minutes and the client gives up long
// before -- and e2e-slot's shim falls back to a local browser for that run.
//
// THE GPU ON WINDOWS. A Linux client's tests ask for
// `--use-angle=vulkan --enable-features=Vulkan`; on Windows that gives WebGL
// but no WebGPU adapter, and --use-angle=d3d11 gives both. So on win32 this
// host swaps them, as the client's shim does with PW_REMOTE_GPU=d3d11. A launch
// that asks for no GPU is not touched.
//
// GET /json (or /) answers {"ok":true,"versions":[...]}: e2e-slot's health check.

const http = require('http');
const net = require('net');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

function argv(name, dflt) {
	const i = process.argv.indexOf('--' + name);
	if (i < 0) return dflt;
	const v = process.argv[i + 1];
	return v === undefined || v.startsWith('--') ? true : v;
}
const ROOT = path.resolve(String(argv('root', process.env.PW_REMOTE_ROOT || '.')));
const PORT = +argv('port', 39001);
const HOST = String(argv('host', '0.0.0.0'));
const ALLOW = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1',
	...String(argv('allow', '') === true ? '' : argv('allow', '')).split(',').map((s) => s.trim()).filter(Boolean)
		.flatMap((ip) => [ip, '::ffff:' + ip])]);
const INSTALL = argv('install', false) === true;

const log = (...a) => console.log(new Date().toISOString(), ...a);

// Chromium switches that run a program or write where they are told. Matched
// on the switch name, before any '='.
const REFUSED_SWITCHES = /^--(renderer-cmd-prefix|utility-cmd-prefix|gpu-launcher|ppapi-plugin-launcher|plugin-launcher|nacl-gdb|browser-subprocess-path|gpu-sandbox-start-early|user-data-dir|log-file|crash-dumps-dir|load-extension|disable-extensions-except|remote-debugging-pipe|remote-debugging-port|remote-debugging-address)$/;
const DROPPED_OPTIONS = ['executablePath', 'downloadsPath', 'artifactsDir', 'tracesDir', 'env', 'firefoxUserPrefs'];

function installed() {
	let names = [];
	try { names = fs.readdirSync(ROOT); } catch (_) { /* no root yet */ }
	return names.map((n) => /^playwright-(\d+\.\d+\.\d+)$/.exec(n)).filter(Boolean).map((m) => m[1])
		.filter((v) => fs.existsSync(cliOf(v)));
}
const dirOf = (v) => path.join(ROOT, 'playwright-' + v);
const cliOf = (v) => path.join(dirOf(v), 'node_modules', 'playwright', 'cli.js');
const minor = (v) => v.split('.').slice(0, 2).join('.');

// version -> {port, proc, ready: Promise}
const backends = new Map();
const installing = new Map();

function freePort() {
	return new Promise((res, rej) => {
		const s = net.createServer();
		s.once('error', rej);
		s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
	});
}

function childEnv(version) {
	const env = { ...process.env };
	const browsers = path.join(dirOf(version), 'browsers');
	if (fs.existsSync(browsers)) env.PLAYWRIGHT_BROWSERS_PATH = browsers;
	return env;
}

async function backend(version) {
	const have = backends.get(version);
	if (have && have.proc.exitCode === null && !have.proc.killed) return have.ready;
	const port = await freePort();
	const proc = spawn(process.execPath, [cliOf(version), 'run-server', '--port', String(port), '--host', '127.0.0.1', '--unsafe'],
		{ env: childEnv(version), stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
	proc.stdout.on('data', (d) => log(`[pw-${version}]`, String(d).trim()));
	proc.stderr.on('data', (d) => log(`[pw-${version}]`, String(d).trim()));
	proc.on('exit', (code) => { log(`backend ${version} exited (${code})`); backends.delete(version); });
	const ready = (async () => {
		for (let i = 0; i < 100; i++) {
			const ok = await new Promise((res) => {
				const r = http.get({ host: '127.0.0.1', port, path: '/json', timeout: 1000 }, (rs) => { rs.resume(); res(rs.statusCode === 200); });
				r.on('error', () => res(false));
				r.on('timeout', () => { r.destroy(); res(false); });
			});
			if (ok) { log(`backend ${version} on 127.0.0.1:${port}`); return port; }
			if (proc.exitCode !== null) break;
			await new Promise((r) => setTimeout(r, 200));
		}
		proc.kill();
		throw new Error(`playwright ${version} run-server did not start`);
	})();
	backends.set(version, { port, proc, ready });
	return ready;
}

function npmCli() {
	const dir = path.dirname(process.execPath);
	return [path.join(dir, 'node_modules', 'npm', 'bin', 'npm-cli.js'),
		path.join(dir, '..', 'lib', 'node_modules', 'npm', 'bin', 'npm-cli.js')].find((p) => fs.existsSync(p));
}

function installVersion(version) {
	if (installing.has(version)) return;
	const npm = npmCli();
	if (!npm) { log(`cannot install ${version}: npm not found beside ${process.execPath}`); return; }
	const dir = dirOf(version);
	fs.mkdirSync(path.join(dir, 'browsers'), { recursive: true });
	if (!fs.existsSync(path.join(dir, 'package.json'))) fs.writeFileSync(path.join(dir, 'package.json'), '{"private":true}\n');
	const run = (args) => new Promise((res) => {
		const p = spawn(process.execPath, args, { env: childEnv(version), stdio: 'ignore', windowsHide: true });
		p.on('exit', (c) => res(c === 0));
		p.on('error', () => res(false));
	});
	log(`installing playwright ${version}`);
	installing.set(version, (async () => {
		const ok = await run([npm, 'install', '--prefix', dir, '--no-audit', '--no-fund', 'playwright@' + version]) &&
			await run([cliOf(version), 'install', 'chromium']);
		log(`install ${version}: ${ok ? 'done' : 'FAILED'}`);
		installing.delete(version);
	})());
}

// The installed version for a client: its exact version, else the newest with
// its major.minor (Playwright's own rule: 1.62.0 talks to a 1.62.1 server).
function pick(clientVersion) {
	const all = installed();
	if (all.includes(clientVersion)) return clientVersion;
	return all.filter((v) => minor(v) === minor(clientVersion))
		.sort((a, b) => +a.split('.')[2] - +b.split('.')[2]).pop();
}

// --use-angle=vulkan -> d3d11 and no Vulkan feature, on a Windows host only.
// PW_REMOTE_PLATFORM stands in for process.platform (the tests set it).
function mapGpuArgs(args, platform) {
	if (platform !== 'win32' || !args.includes('--use-angle=vulkan')) return args;
	const out = [];
	for (const a of args) {
		if (a === '--use-angle=vulkan') out.push('--use-angle=d3d11');
		else if (/^--enable-features=/.test(a)) {
			const rest = a.slice('--enable-features='.length).split(',').filter((f) => f && f !== 'Vulkan');
			if (rest.length) out.push('--enable-features=' + rest.join(','));
		} else out.push(a);
	}
	return out;
}

// The client's launch options, made safe for an --unsafe backend; a string
// saying why when they cannot be.
function sanitize(raw, platform = process.env.PW_REMOTE_PLATFORM || process.platform) {
	if (!raw) return { value: '' };
	let o;
	try { o = JSON.parse(raw); } catch (_) { return { error: 'launch options are not JSON' }; }
	if (!o || typeof o !== 'object') return { error: 'launch options are not an object' };
	for (const k of DROPPED_OPTIONS) delete o[k];
	if (o.args !== undefined) {
		if (!Array.isArray(o.args) || o.args.some((a) => typeof a !== 'string')) return { error: 'args must be strings' };
		const bad = o.args.find((a) => REFUSED_SWITCHES.test(a.split('=')[0]));
		if (bad) return { error: `the switch ${bad.split('=')[0]} is not allowed on a shared browser host` };
		o.args = mapGpuArgs(o.args, platform);
	}
	return { value: JSON.stringify(o) };
}

function refuse(socket, code, text) {
	log(`refused ${socket.remoteAddress}: ${code} ${text}`);
	socket.end(`HTTP/1.1 ${code} ${http.STATUS_CODES[code]}\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n${text}\n`);
}

const server = http.createServer((req, res) => {
	if (!ALLOW.has(req.socket.remoteAddress)) { req.socket.destroy(); return; }
	if (req.method === 'GET' && (req.url === '/json' || req.url === '/')) {
		res.setHeader('Content-Type', 'application/json');
		res.end(JSON.stringify({ ok: true, versions: installed(), running: [...backends.keys()], installing: [...installing.keys()] }) + '\n');
		return;
	}
	res.statusCode = 404;
	res.end('not found\n');
});

server.on('upgrade', async (req, socket, head) => {
	const who = socket.remoteAddress;
	if (!ALLOW.has(who)) { socket.destroy(); return; }
	socket.on('error', () => {});
	const m = /^Playwright\/(\d+\.\d+\.\d+)/.exec(req.headers['user-agent'] || '');
	if (!m) return refuse(socket, 400, 'not a Playwright client (no Playwright/x.y.z User-Agent)');
	const version = pick(m[1]);
	if (!version) {
		if (INSTALL && /^\d+\.\d+\.\d+$/.test(m[1])) {
			installVersion(m[1]);
			return refuse(socket, 503, `playwright ${m[1]} is being installed on this host; retry in a few minutes`);
		}
		return refuse(socket, 503, `playwright ${minor(m[1])}.x is not installed on this host (have: ${installed().join(', ') || 'none'})`);
	}
	const url = new URL(req.url, 'http://x');
	const fromQuery = url.searchParams.get('launch-options');
	url.searchParams.delete('launch-options');
	const header = req.headers['x-playwright-launch-options'];
	const s = sanitize(fromQuery || (Array.isArray(header) ? header[0] : header) || '');
	if (s.error) return refuse(socket, 403, s.error);
	let port;
	try { port = await backend(version); } catch (e) { return refuse(socket, 503, String(e.message || e)); }
	const headers = { ...req.headers, host: '127.0.0.1:' + port };
	delete headers['x-playwright-launch-options'];
	if (s.value) headers['x-playwright-launch-options'] = s.value;
	const up = net.connect(port, '127.0.0.1');
	const started = Date.now();
	up.on('connect', () => {
		let head1 = `${req.method} ${url.pathname}${url.search} HTTP/1.1\r\n`;
		for (const [k, v] of Object.entries(headers)) for (const one of [].concat(v)) head1 += `${k}: ${one}\r\n`;
		up.write(head1 + '\r\n');
		if (head && head.length) up.write(head);
		socket.pipe(up).pipe(socket);
		log(`open ${who} playwright ${m[1]} -> ${version}`);
	});
	let closed = false;
	const close = () => {
		if (closed) return;
		closed = true;
		log(`close ${who} after ${Math.round((Date.now() - started) / 1000)}s`);
		socket.destroy();
		up.destroy();
	};
	up.on('error', close);
	up.on('close', close);
	socket.on('close', close);
});

server.listen(PORT, HOST, () => log(`pw-remote-server on ${HOST}:${PORT}, root ${ROOT}, versions ${installed().join(', ') || 'none'}, allow ${[...ALLOW].filter((a) => !a.startsWith('::ffff:')).join(',')}${INSTALL ? ', --install' : ''}`));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { for (const b of backends.values()) b.proc.kill(); process.exit(0); });
