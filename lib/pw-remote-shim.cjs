'use strict';
// pw-remote-shim.cjs -- e2e-slot's remote slots: the test stays here, the
// browser runs on another machine.
//
//   NODE_OPTIONS="--require /path/to/pw-remote-shim.cjs" PW_REMOTE_WS=ws://host:port/ node test.cjs
//
// e2e-slot sets both when it hands out a remote slot; nothing else should need
// to. With PW_REMOTE_WS unset this file does nothing at all, so a stray
// NODE_OPTIONS costs one `require`.
//
// WHAT IT CHANGES. The first time any module loads Playwright (playwright,
// playwright-core, @playwright/test -- whichever the lane's node_modules has),
// its `chromium` object gets a new launch(): instead of starting Chromium here
// it connects to the Playwright server at PW_REMOTE_WS and has THAT machine
// launch one, with the same options. The test gets an ordinary Browser back and
// cannot tell, which is the point: no lane's tests change to use a remote slot.
//
// WHY THE DEV SERVER STILL WORKS. The remote browser's localhost is the remote
// machine, not this one. exposeNetwork makes Playwright tunnel matching hosts
// back through the connection and open them from HERE, so `https://localhost:5466`
// reaches the lane's vite server on this box. "Matching" is <loopback> plus every
// name /etc/hosts points at a loopback address, because a lane's APP_URL is often
// such a name (theprototype.app is 127.0.0.1 on the Deck, and the real site on
// the PC). PW_REMOTE_EXPOSE replaces the list when it is set.
//
// WHAT IT DOES NOT MOVE, and runs here instead, with one line on stderr:
//   - launchPersistentContext: a profile directory on this disk cannot be
//     opened by a browser on another one, and connect() has no such call.
//   - headless: false: the remote machine's browser runs in a service session
//     with nobody looking at it; a headed run is for a person watching here.
//   - firefox and webkit: the remote side installs Chromium only.
//   - launch() when the remote server does not answer (PW_REMOTE_FALLBACK=local,
//     the default): a lane's battery then runs on this box, slower, rather than
//     failing every suite for a reason that has nothing to do with the code.
//     PW_REMOTE_FALLBACK=fail makes it an error instead.
//
// DOWNLOADS. download.path() throws on a connected browser ("Path is not
// available when connecting remotely"); six core suites call it. Here it
// saves the download under TMPDIR with saveAs() and returns that path, so those
// suites pass unchanged. The files are removed when the process exits.
//
// THE GPU ON A WINDOWS HOST (PW_REMOTE_GPU=d3d11; e2e-slot sets it from
// MUXTOPUS_E2E_REMOTE_GPU). A test picks its GPU flags from THIS machine's
// platform, so on Linux it asks for `--use-angle=vulkan --enable-features=Vulkan`.
// On a Windows host that gives WebGL on the card but no WebGPU adapter
// (requestAdapter() is null); --use-angle=d3d11 gives both. With d3d11 set, a
// launch whose args name --use-angle=vulkan gets d3d11 instead and loses the
// Vulkan feature -- what lib/pw-pc-shim.cjs does for WSL's d3d12 driver. Only
// the args sent to the remote host change: a local fallback keeps Vulkan, and
// a launch that asks for no GPU keeps SwiftShader wherever it runs.
//
// VERSIONS. Playwright refuses a server whose major.minor differs from the
// client's (HTTP 428 "Playwright version mismatch"). The remote side
// (pw-remote-server.cjs) keeps one run-server per version and picks it from the
// User-Agent the client sends, so lanes on 1.62 and 1.63 share one remote slot.

const WS = process.env.PW_REMOTE_WS || '';
if (WS && !global.__muxPwRemoteShim) {
	global.__muxPwRemoteShim = true;
	install();
}

function install() {
	const Module = require('module');
	const fs = require('fs');
	const os = require('os');
	const path = require('path');
	const FALLBACK = (process.env.PW_REMOTE_FALLBACK || 'local') === 'fail' ? 'fail' : 'local';
	// A connect that has not answered in this long is a sleeping or unplugged
	// host, not a slow one: the server answers a healthy connect in well under a
	// second on a LAN.
	const CONNECT_MS = +process.env.PW_REMOTE_CONNECT_MS || 30000;
	const quiet = !!process.env.PW_REMOTE_QUIET;
	const said = new Set();
	const say = (key, msg) => {
		if (said.has(key)) return;
		said.add(key);
		if (!quiet || key.startsWith('!')) process.stderr.write('pw-remote-shim: ' + msg + '\n');
	};

	// Options that name something on THIS machine, or that cannot cross a
	// websocket. The server would drop most of them anyway (filterLaunchOptions);
	// dropping them here keeps the header honest about what the browser got.
	const LOCAL_ONLY = ['executablePath', 'env', 'logger', 'downloadsPath', 'tracesDir', 'artifactsDir',
		'handleSIGINT', 'handleSIGTERM', 'handleSIGHUP', 'devtools'];

	const GPU = process.env.PW_REMOTE_GPU === 'd3d11' ? 'd3d11' : '';
	function mapArgs(args) {
		if (!GPU || !Array.isArray(args) || !args.includes('--use-angle=vulkan')) return args;
		const out = [];
		for (const a of args) {
			if (a === '--use-angle=vulkan') out.push('--use-angle=' + GPU);
			else if (typeof a === 'string' && /^--enable-features=/.test(a)) {
				const rest = a.slice('--enable-features='.length).split(',').filter((f) => f && f !== 'Vulkan');
				if (rest.length) out.push('--enable-features=' + rest.join(','));
			} else out.push(a);
		}
		say('gpu', '--use-angle=vulkan -> ' + GPU + ' on ' + WS + ' (PW_REMOTE_GPU; Vulkan has no WebGPU adapter on a Windows host)');
		return out;
	}

	// The names /etc/hosts points at this machine. '*' and ',' would widen or
	// split the pattern Playwright parses, so a name carrying one is skipped.
	const loopNames = new Set();
	try {
		for (const line of fs.readFileSync('/etc/hosts', 'utf8').split('\n')) {
			const f = line.replace(/#.*/, '').trim().split(/\s+/);
			if (f.length < 2 || !/^(127\.|::1$)/.test(f[0])) continue;
			for (const n of f.slice(1)) if (n && !/[*,]/.test(n)) loopNames.add(n.toLowerCase());
		}
	} catch (_) { /* no /etc/hosts: loopback only */ }
	const EXPOSE = process.env.PW_REMOTE_EXPOSE !== undefined ? process.env.PW_REMOTE_EXPOSE
		: ['<loopback>', ...loopNames].join(',');

	// BOTH LOOPBACKS FOR THOSE NAMES. Playwright opens a tunnelled host from
	// here by looking it up once per family (dualStackLookup) and trying what it
	// gets. `127.0.0.1 theprototype.app` has no IPv6 answer, so only 127.0.0.1
	// is tried -- and vite listens on [::1] alone ("Local: https://localhost"),
	// so every page failed with ERR_SOCKS_CONNECTION_FAILED (measured on the
	// Deck, phase 1). A local Chromium reaches it because the system resolver
	// gives it ::1 as well. So a name the hosts file puts on this machine
	// answers ::1 for IPv6 and 127.0.0.1 for IPv4, and happy eyeballs takes
	// whichever is listening.
	const dns = require('dns');
	const realLookup = dns.promises.lookup;
	dns.promises.lookup = function (host, opts, ...rest) {
		const fam = opts && typeof opts === 'object' ? opts.family : opts;
		if (typeof host === 'string' && loopNames.has(host.toLowerCase()) && (fam === 4 || fam === 6)) {
			const one = { address: fam === 6 ? '::1' : '127.0.0.1', family: fam };
			return Promise.resolve(opts && opts.all ? [one] : one);
		}
		return realLookup.call(this, host, opts, ...rest);
	};

	const tmpDirs = [];
	process.on('exit', () => {
		for (const d of tmpDirs) try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best effort */ }
	});

	// download.path() on a connected browser: save a local copy once, hand that
	// path out. Patched on the prototype the first time a download is seen,
	// since the client classes are not exported.
	const patchedProtos = new WeakSet();
	function patchDownload(dl) {
		const proto = Object.getPrototypeOf(dl);
		if (!proto || patchedProtos.has(proto) || typeof proto.path !== 'function') return;
		patchedProtos.add(proto);
		const realPath = proto.path;
		proto.path = async function () {
			try {
				return await realPath.call(this);
			} catch (e) {
				if (!/connecting remotely/.test(String(e && e.message))) throw e;
				if (!this.__muxLocalPath) {
					const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pw-remote-dl-'));
					tmpDirs.push(dir);
					const file = path.join(dir, this.suggestedFilename() || 'download');
					await this.saveAs(file);
					this.__muxLocalPath = file;
				}
				return this.__muxLocalPath;
			}
		};
	}
	function watchContext(ctx) {
		const onPage = (p) => p.on('download', patchDownload);
		ctx.on('page', onPage);
		for (const p of ctx.pages()) onPage(p);
	}
	function adapt(browser) {
		// newPage() goes through this.newContext(), so one wrapper covers both.
		const realNewContext = browser.newContext;
		browser.newContext = async function (...a) {
			const ctx = await realNewContext.apply(this, a);
			watchContext(ctx);
			return ctx;
		};
		return browser;
	}

	function patch(chromium) {
		if (!chromium || chromium.__muxRemote || typeof chromium.launch !== 'function' || typeof chromium.connect !== 'function') return;
		chromium.__muxRemote = true;
		const realLaunch = chromium.launch;
		const realPersistent = chromium.launchPersistentContext;
		chromium.launch = async function (options = {}) {
			if (options && options.headless === false) {
				say('headed', 'a headed launch runs on this machine, not on ' + WS);
				return realLaunch.call(this, options);
			}
			const sent = {};
			for (const [k, v] of Object.entries(options || {})) {
				if (LOCAL_ONLY.includes(k)) {
					if (k === 'executablePath' && v) say('exe', 'executablePath ' + v + ' ignored: the remote side uses its own Chromium');
					continue;
				}
				if (typeof v !== 'function') sent[k] = v;
			}
			if (sent.args) sent.args = mapArgs(sent.args);
			try {
				const browser = await this.connect(WS, {
					headers: { 'x-playwright-launch-options': JSON.stringify(sent) },
					exposeNetwork: EXPOSE,
					timeout: CONNECT_MS,
					slowMo: options.slowMo
				});
				say('on', 'chromium on ' + WS + ' (exposing ' + EXPOSE + ')');
				return adapt(browser);
			} catch (e) {
				const why = String((e && e.message) || e).split('\n').find((l) => l.trim()) || 'no answer';
				if (FALLBACK === 'fail') throw e;
				say('!fallback', 'remote browser at ' + WS + ' failed (' + why.trim().slice(0, 200) + '); launching here instead');
				return realLaunch.call(this, options);
			}
		};
		if (typeof realPersistent === 'function') {
			chromium.launchPersistentContext = function (...a) {
				say('persistent', 'launchPersistentContext runs on this machine: a profile directory cannot be opened remotely');
				return realPersistent.apply(this, a);
			};
		}
	}

	// Every module load is checked, but only a request that names Playwright is
	// looked at further -- a getter on some unrelated export must not run here.
	const realLoad = Module._load;
	Module._load = function (request, ...rest) {
		const exp = realLoad.call(this, request, ...rest);
		if (typeof request === 'string' && request.includes('playwright')) {
			try { patch(exp && exp.chromium); } catch (_) { /* leave it local */ }
		}
		return exp;
	};
}
