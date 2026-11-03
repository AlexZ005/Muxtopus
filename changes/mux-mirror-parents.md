## e2e-slot: a file input no longer blocks the pc slot for later runs

- A pc slot that mirrored a single file (a scene file inside a scenes checkout) made that file's folders on the host without the `.muxtopus-mirror` marker. A later run whose input was a folder in that tree was then refused as "a folder of this machine's own", and it waited for a slower slot every time. The folders a mirror makes now carry the marker on the topmost one, for file and folder inputs alike. A folder that was already on the host is still never marked, and still refused.
- `docs/pc-host.md` says how to clear a folder an older version left unmarked: `touch <folder>/.muxtopus-mirror` on the host.
