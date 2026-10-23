## e2e slots: two fixes

- **A pc slot no longer forwards this machine's slot choice.** `E2E_SLOTS`, `E2E_SLOT_LOCK`, `E2E_PREFER`, `E2E_REMOTE` and `E2E_PC` are no longer sent with a run. The pc host's own `e2e-slot` read them and warned that it had no `hosts.conf`. With `E2E_SLOT_LOCK` set, it would also have taken its local slot outside the lock files its own lanes share.
- **`e2e-slot --help` prints its usage.** It used to take a slot and run `--help` as the command (exit 127). On a machine with pc slots, that run went to the pc.
