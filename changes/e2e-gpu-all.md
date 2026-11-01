## e2e-slot: a whole battery on the host's GPU

- New setting `MUXTOPUS_E2E_GPU_ALL` (`off`, the default, or `on`; `E2E_GPU_ALL` for one run). With `on`, a remote or pc slot gives a browser launch that names no GPU path the host's GPU instead of SwiftShader. On a PC with an RTX-class card nine suites took 5 minutes instead of 16, and the VM's CPU fell from about 60 % to about 6 %, so the same host can carry more slots.
- A launch that names `--use-angle=`, `--use-gl=` or `--disable-gpu` keeps what it named, so a suite that needs software GL can stay on it.
- `docs/pc-host.md` now says that a distro does not come back by itself after `wsl --shutdown`.
