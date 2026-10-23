'use strict';
// pw-pc-shim.cjs -- e2e-slot's pc slots: the GPU a WSL distro actually has.
//
//   NODE_OPTIONS="--require /path/to/pw-pc-shim.cjs" PW_PC_GPU=d3d12 node test.cjs
//
// lib/e2e-pc-remote.sh puts it in NODE_OPTIONS on a pc slot whose host has a
// usable /dev/dxg (WSL2 with a Windows GPU driver). With PW_PC_GPU unset, or
// anything but d3d12, it does nothing.
//
// WHY. Tests that want a real GPU pass ANGLE flags picked for the machine they
// were written on: `--use-angle=vulkan --enable-features=Vulkan` on Linux. In
// WSL2 there is no Vulkan driver for the Windows GPU, so that Chromium gets
// Mesa's llvmpipe -- a CPU rasteriser, quietly. What WSL does have is Mesa's
// d3d12 Gallium driver over /dev/dxg, reached through EGL. MEASURED in an
// Ubuntu 24.04 distro on a Windows 11 PC with an RTX-class card, the same
// Chromium, WEBGL_debug_renderer_info:
//   (no GPU flags)                 ANGLE (Google, Vulkan 1.3.0 (SwiftShader ...))
//   --use-angle=vulkan             ANGLE (Mesa, Vulkan 1.4 (llvmpipe ...))
//   --use-angle=gl-egl             ANGLE (Mesa, llvmpipe ..., OpenGL ES 3.2)
//   --use-angle=gl-egl + GALLIUM_DRIVER=d3d12
//                                  ANGLE (Microsoft Corporation, D3D12 (<the card>), OpenGL ES 3.1)
// So on a launch that ASKS for a GPU (its args name --use-angle=vulkan), this
// swaps in gl-egl and drops the Vulkan feature; the environment half
// (GALLIUM_DRIVER=d3d12, the WSL driver folder on LD_LIBRARY_PATH) is set by
// the remote runner for the whole command. A launch that asks for no GPU keeps
// SwiftShader, exactly as it would anywhere else -- a test's numbers must not
// change because of where it ran unless it asked for the GPU.
//
// It is still not the Deck's GPU: a frame-rate gate measures this machine.
// Those runs take `e2e-slot --local` or `--exclusive`, which never use a pc
// slot.

if ((process.env.PW_PC_GPU || '') === 'd3d12' && !global.__muxPwPcShim) {
	global.__muxPwPcShim = true;
	install();
}

function install() {
	const Module = require('module');
	let said = false;

	function mapArgs(args) {
		if (!Array.isArray(args) || !args.includes('--use-angle=vulkan')) return args;
		const out = [];
		for (const a of args) {
			if (a === '--use-angle=vulkan') out.push('--use-angle=gl-egl');
			else if (/^--enable-features=/.test(a)) {
				const rest = a.slice('--enable-features='.length).split(',').filter((f) => f && f !== 'Vulkan');
				if (rest.length) out.push('--enable-features=' + rest.join(','));
			} else out.push(a);
		}
		if (!said) {
			said = true;
			process.stderr.write('pw-pc-shim: --use-angle=vulkan -> gl-egl (the d3d12 driver; WSL has no Vulkan for this GPU)\n');
		}
		return out;
	}

	function patch(chromium) {
		if (!chromium || chromium.__muxPc || typeof chromium.launch !== 'function') return;
		chromium.__muxPc = true;
		for (const name of ['launch', 'launchPersistentContext', 'launchServer']) {
			const real = chromium[name];
			if (typeof real !== 'function') continue;
			// launchPersistentContext takes (userDataDir, options); the others (options).
			const at = name === 'launchPersistentContext' ? 1 : 0;
			chromium[name] = function (...a) {
				const o = a[at];
				if (o && typeof o === 'object' && Array.isArray(o.args)) a[at] = { ...o, args: mapArgs(o.args) };
				return real.apply(this, a);
			};
		}
	}

	const realLoad = Module._load;
	Module._load = function (request, ...rest) {
		const exp = realLoad.call(this, request, ...rest);
		if (typeof request === 'string' && request.includes('playwright')) {
			try { patch(exp && exp.chromium); } catch (_) { /* leave it as it was */ }
		}
		return exp;
	};
}
