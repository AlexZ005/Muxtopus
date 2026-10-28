## e2e-slot: WebGPU on a Windows browser host

- New setting `MUXTOPUS_E2E_REMOTE_GPU` (`keep`, the default, or `d3d11`; `E2E_REMOTE_GPU` for one run). With `d3d11`, a remote slot sends a test's `--use-angle=vulkan` as `--use-angle=d3d11` and drops the `Vulkan` feature. On a Windows browser host the Vulkan flags gave WebGL but no WebGPU adapter; d3d11 gives both. A launch that asks for no GPU is not changed.
- `pw-remote-server.cjs` running on Windows now makes the same change itself, so a redeployed host needs no setting on the client.

- On a Windows host the d3d11 mapping also turns off DXC (`--disable-dawn-features=use_dxc`), so WebGPU tests get a working device, not just an adapter
