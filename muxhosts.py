#!/usr/bin/env python3
"""muxhosts -- the other machines in hosts.conf, from Python, and the one
thing that keeps a folder the same on both: the handover sync.

    python3 muxhosts.py names                         the hosts the file defines
    python3 muxhosts.py get <host> <key> [default]    one key
    python3 muxhosts.py sync <host> <dir> <manifest> [--dry-run]

THE FILE is lib/hosts.sh's: ~/.config/muxtopus/hosts.conf (MUXTOPUS_HOSTS
moves it), one [section] per host, `key = value`, `#` comments. The two
readers must agree, and tests/test_hosts.py holds them to it.

WHY A SYNC AND NOT A MOUNT. A lane on the pc host writes its STATUS and
QUESTIONS files where its brief says, ~/.code/handovers/..., and this machine's
handover.sh, dashboard and orchestrator read them here; `handover.sh done`
moves one into done/ on whichever machine runs it. A mount would do that with
no code, but the far machine would have to log in HERE -- a key on the pc that
opens this machine's whole account, since sftp cannot be held to one folder
without a chroot -- and every lane there would hang on the folder whenever
this machine slept. So this machine, which already reaches the pc, keeps the
two folders the same, once a watchdog pass.

HOW, unison's rule: a MANIFEST records every file as it was after the last
sync (mtime and size). For each file, whichever side differs from the
manifest changed, and its version goes to the other side -- a new or edited
file is copied, a removed one is removed, so a move into done/ (a removal
plus a new file) travels as a move. Both changed: the newer one wins, and a
file one side removed and the other edited is kept. NOTHING IS EVER DELETED
WITHOUT A MANIFEST: the first sync of a pair only copies (newer wins), so a
lost or new manifest can resurrect a moved file but never lose one. Copies
are rsync -a, which keeps mtimes, so the next pass sees both sides equal.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys


def hosts_file() -> pathlib.Path:
    if os.environ.get("MUXTOPUS_HOSTS"):
        return pathlib.Path(os.environ["MUXTOPUS_HOSTS"])
    cfg = os.environ.get("MUXTOPUS_CONFIG") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "muxtopus", "config")
    return pathlib.Path(cfg).parent / "hosts.conf"


def load(path: pathlib.Path | None = None) -> dict[str, dict[str, str]]:
    """{host: {key: value}}. A missing file is no hosts, never an error."""
    path = path or hosts_file()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, dict[str, str]] = {}
    cur = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[([A-Za-z0-9_.-]+)\]", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, {})
            continue
        if line.startswith("["):
            cur = None          # a section name lib/hosts.sh would not list either
            continue
        if cur is not None and "=" in line:
            k, v = line.split("=", 1)
            out[cur][k.strip()] = v.strip()
    return out


def get(host: str, key: str, default: str = "") -> str:
    return load().get(host, {}).get(key, "") or default


def ssh_argv(host: str) -> list[str] | None:
    """lib/hosts.sh mux_host_ssh, the same options in the same order."""
    h = load().get(host, {})
    target = h.get("ssh", "")
    if not target:
        return None
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=" + os.environ.get("MUX_HOST_TIMEOUT", "5"),
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4", "-o", "ControlMaster=no",
            "-o", "ControlPath=" + os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/muxtopus-ssh-%C"]
    if h.get("port"):
        argv += ["-p", h["port"]]
    if h.get("key"):
        argv += ["-i", os.path.expanduser(h["key"]), "-o", "IdentitiesOnly=yes"]
    return argv + [target]


# ------------------------------------------------------------------ sync
# Files that are never synced: editors' and our own temporaries.
SKIP = re.compile(r"(^|/)(\.[^/]*\.sw.|[^/]*~|[^/]*\.tmp|\.muxsync[^/]*)$")


def local_state(root: pathlib.Path) -> dict[str, list[int]]:
    out = {}
    for dp, _dn, fn in os.walk(root):
        for n in fn:
            p = pathlib.Path(dp) / n
            rel = p.relative_to(root).as_posix()
            if SKIP.search(rel):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            out[rel] = [int(st.st_mtime), st.st_size]
    return out


def remote_state(ssh: list[str], root: str) -> dict[str, list[int]] | None:
    cmd = "mkdir -p %s && cd %s && find . -type f -printf '%%P\\t%%T@\\t%%s\\n'" % (shlex.quote(root), shlex.quote(root))
    try:
        r = subprocess.run(ssh + [cmd], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.splitlines():
        f = line.split("\t")
        if len(f) != 3 or SKIP.search(f[0]):
            continue
        try:
            out[f[0]] = [int(float(f[1])), int(f[2])]
        except ValueError:
            continue
    return out


def plan(loc: dict, rem: dict, man: dict | None) -> tuple[list, list, list, list]:
    """(push, pull, delete_here, delete_there) -- the decision, pure, for the tests."""
    push, pull, del_l, del_r = [], [], [], []
    for rel in sorted(set(loc) | set(rem) | set(man or {})):
        l, r = loc.get(rel), rem.get(rel)
        m = (man or {}).get(rel)
        if l == r:
            continue
        if man is not None and m is not None and l == m:      # only the far side changed
            (del_l if r is None else pull).append(rel)
        elif man is not None and m is not None and r == m:    # only this side changed
            (del_r if l is None else push).append(rel)
        elif l is None:                                       # new there, or kept over a removal here
            pull.append(rel)
        elif r is None:
            push.append(rel)
        elif r[0] > l[0]:                                     # both changed: the newer wins
            pull.append(rel)
        else:
            push.append(rel)
    return push, pull, del_l, del_r


def _rsync(ssh: list[str], files: list[str], src: str, dst: str) -> bool:
    if not files:
        return True
    rsh = " ".join(shlex.quote(a) for a in ssh[:-1])
    r = subprocess.run(["rsync", "-a", "--from0", "--files-from=-", "-e", rsh, src, dst],
                       input="\0".join(files).encode(), capture_output=True, timeout=300)
    if r.returncode not in (0, 24):   # 24: a file vanished while being copied -- the next pass sees it
        print(f"muxhosts: rsync {src} -> {dst}: rc {r.returncode}: {r.stderr.decode(errors='replace').strip()[-300:]}",
              file=sys.stderr)
        return False
    return True


def sync(host: str, root: str, manifest: str, dry: bool = False) -> int:
    ssh = ssh_argv(host)
    if not ssh:
        print(f"muxhosts: no host {host!r} in {hosts_file()}", file=sys.stderr)
        return 2
    rootp = pathlib.Path(root)
    rootp.mkdir(parents=True, exist_ok=True)
    rem = remote_state(ssh, root)
    if rem is None:
        print(f"muxhosts: {host} did not answer", file=sys.stderr)
        return 1
    loc = local_state(rootp)
    try:
        man = json.loads(pathlib.Path(manifest).read_text())
    except (OSError, ValueError):
        man = None
    push, pull, del_l, del_r = plan(loc, rem, man)
    for rel, what in [(p, "push") for p in push] + [(p, "pull") for p in pull] + \
                     [(p, "remove here") for p in del_l] + [(p, "remove there") for p in del_r]:
        print(f"{what}\t{rel}")
    if dry:
        return 0
    target = ssh[-1]
    ok = _rsync(ssh, push, root.rstrip("/") + "/", f"{target}:{root.rstrip('/')}/")
    ok = _rsync(ssh, pull, f"{target}:{root.rstrip('/')}/", root.rstrip("/") + "/") and ok
    for rel in del_l:
        try:
            (rootp / rel).unlink()
        except OSError:
            pass
    if del_r:
        cmd = "cd %s && rm -f -- %s" % (shlex.quote(root), " ".join(shlex.quote(r) for r in del_r))
        subprocess.run(ssh + [cmd], capture_output=True, timeout=60)
    # The manifest is what BOTH sides hold now: read again rather than
    # computed, so a copy that failed is not recorded as done.
    if ok:
        loc2, rem2 = local_state(rootp), remote_state(ssh, root)
        if rem2 is not None:
            same = {k: v for k, v in loc2.items() if rem2.get(k) == v}
            tmp = pathlib.Path(manifest + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(same, sort_keys=True))
            os.replace(tmp, manifest)
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "names":
        for n in load():
            print(n)
        return 0
    if len(argv) >= 3 and argv[0] == "get":
        print(get(argv[1], argv[2], argv[3] if len(argv) > 3 else ""))
        return 0
    if len(argv) >= 4 and argv[0] == "sync":
        return sync(argv[1], argv[2], argv[3], dry="--dry-run" in argv[4:])
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
