#!/usr/bin/env python3
"""muxtelegram -- the phone's half of the watchdog's notifications. Stdlib only.

    python3 muxtelegram.py poll
        once per watchdog pass: read the bot's updates and obey the ones that
        came from TELEGRAM_CHAT and name a pending action. Exits at once when
        another process holds the lock (the other account's daemon, or the
        setup guide waiting for a press).
    python3 muxtelegram.py prompt-message --profile P --pane %N --sha X
            --yes 0|1 --more 0|1 --title T --body B
        send a `waiting` message with Yes / No / More, retiring any earlier
        message for the same pane. Prints the message_id.
    python3 muxtelegram.py retire TARGET NOTE
        forget every pending action for TARGET (e.g. prompt:%12) and edit its
        message to say NOTE.
    python3 muxtelegram.py questions [--profile P]
        every UNANSWERED QUESTIONS file of one account, both folders, as JSON
        lines: {path, slug, legacy, title, forks: [{id, title, text}]}.

docs/plan-notify-telegram.md §3, §3b. NO DAEMON, NO WEBHOOK, NO PORT: the
watchdog calls `poll` with timeout=0, so latency is one pass.

ONE POLLER PER BOT. getUpdates has a single consumer and both accounts'
daemons share one bot, so the offset, the lock and the pending actions live in
ONE per-machine folder, $XDG_STATE_HOME/muxtopus-notify/:

    lock                 flock(2); claude-notify.sh --setup takes it too
    offset               the next update_id, written BEFORE an update is acted
                         on -- a crash loses a press rather than typing twice
    pending/<id>.json    one per BUTTON: {id, group, kind, action, target,
                         profile, pane, prompt_sha, path, fork_id, option,
                         message_id, created}. The id is the callback data
                         (Telegram caps that at 64 bytes, so it is opaque).
    groups/<gid>.json    one per MESSAGE: {gid, target, message_id, text,
                         created}. A press consumes its whole group.

RE-ISSUE SUPERSEDES. Every group names its TARGET -- `prompt:<pane>`,
`fork:<path>#<fork_id>` -- and issuing a new group for a target retires the old
one first: its ids are deleted (a stale button can never fire twice) and its
message is edited to say it was superseded. /pending (§3b) is built on this.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import muxconfig  # noqa: E402

try:                                    # handover-visibility's reader, when it exists
    import muxhandovers                 # type: ignore  # noqa: E402
except ImportError:                     # pragma: no cover - depends on the tree
    muxhandovers = None

STATE_HOME = pathlib.Path(os.environ.get("XDG_STATE_HOME")
                          or str(pathlib.Path.home() / ".local" / "state"))
SHARED = STATE_HOME / "muxtopus-notify"
NOTIFY_LOG = STATE_HOME / "claude-watchdog" / "notify.log"
EXPIRE = 24 * 3600
MORE_LINES = 60
TEXT_MAX = 3900


# ------------------------------------------------------------------ basics
def log(msg: str) -> None:
    conf = read_conf()
    if conf.get("TELEGRAM_TOKEN"):
        msg = msg.replace(conf["TELEGRAM_TOKEN"], "<token>")
    try:
        NOTIFY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTIFY_LOG, "a") as f:
            f.write("%s  telegram: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


_CONF = None


def conf_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CLAUDE_NOTIFY_CONF")
                        or str(pathlib.Path.home() / ".config" / "claude-notify.conf"))


def read_conf() -> dict:
    """claude-notify.conf as KEY=VALUE lines -- the shape --setup writes and
    the header documents. A READER: nothing in the file is executed."""
    global _CONF
    if _CONF is not None:
        return _CONF
    out = {}
    try:
        for line in conf_path().read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if not v.startswith(("'", '"')):
                v = v.split("#", 1)[0].strip()
            out[k.strip()] = v.strip("'\"")
    except OSError:
        pass
    api = os.environ.get("TELEGRAM_API") or out.get("TELEGRAM_API") or "https://api.telegram.org"
    out["TELEGRAM_API"] = api.rstrip("/")
    _CONF = out
    return out


def telegram_ready() -> bool:
    c = read_conf()
    return c.get("BACKEND") == "telegram" and bool(c.get("TELEGRAM_TOKEN")) and bool(c.get("TELEGRAM_CHAT"))


def api(method: str, **params) -> dict:
    """One Bot API call. Never raises, never lets the URL (which holds the
    token) into a message: Telegram's own description or a bare error class."""
    c = read_conf()
    url = "%s/bot%s/%s" % (c["TELEGRAM_API"], c.get("TELEGRAM_TOKEN", ""), method)
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
            for k, v in params.items() if v is not None}
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except (ValueError, OSError):
            return {"ok": False, "description": "HTTP %s" % e.code}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "description": type(e).__name__}


def clip(text: str, n: int = TEXT_MAX) -> str:
    return text if len(text) <= n else text[:n - 2] + " …"


def write_json(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def read_json(path: pathlib.Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def locked(wait: float | None):
    """The one-poller lock. wait=None: do not wait at all (yield False when it
    is held). Otherwise wait up to that many seconds, then carry on unlocked
    rather than lose a message."""
    SHARED.mkdir(parents=True, exist_ok=True)
    f = open(SHARED / "lock", "w")
    got = False
    try:
        deadline = time.time() + (wait or 0)
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if wait is None or time.time() >= deadline:
                    break
                time.sleep(0.1)
        yield got
    finally:
        if got:
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def knob(key: str, profile: str) -> str:
    return muxconfig.knob(key, profile, "") or ""


def watchdog(profile: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [str(HERE / "claude-watchdog.sh")]
    if profile:
        cmd += ["--profile", profile]
    return subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=30)


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=15)


# ------------------------------------------------------------ the store
def pending_dir() -> pathlib.Path:
    return SHARED / "pending"


def groups_dir() -> pathlib.Path:
    return SHARED / "groups"


def groups_for(target: str) -> list[dict]:
    out = []
    for p in sorted(groups_dir().glob("*.json")):
        g = read_json(p)
        if g and g.get("target") == target:
            out.append(g)
    return out


def drop_group(gid: str) -> None:
    for p in pending_dir().glob("*.json"):
        d = read_json(p)
        if d is None or d.get("group") == gid:
            p.unlink(missing_ok=True)
    (groups_dir() / (gid + ".json")).unlink(missing_ok=True)


def edit_note(group: dict, note: str, text: str | None = None) -> None:
    """Rewrite a message as its original text plus what became of it, with no
    buttons -- the chat is the audit trail."""
    mid = group.get("message_id")
    if not mid:
        return
    body = clip((text or group.get("text") or "").rstrip() + "\n\n" + note)
    r = api("editMessageText", chat_id=read_conf().get("TELEGRAM_CHAT"), message_id=mid, text=body)
    if not r.get("ok"):
        log("edit of message %s failed: %s" % (mid, r.get("description")))


def retire(target: str, note: str) -> int:
    """Forget every group for TARGET and edit their messages. Returns how many."""
    n = 0
    for g in groups_for(target):
        drop_group(g["gid"])
        edit_note(g, note)
        n += 1
    if n:
        log("retired %d message(s) for %s: %s" % (n, target, note))
    return n


def issue(target: str, kind: str, profile: str, actions: list[tuple[str, str]],
          extra: dict, text: str) -> tuple[str, list[dict]]:
    """A NEW group for TARGET, superseding any earlier one. Returns the gid and
    the inline keyboard rows (one row). Ids are bound to the message_id by
    bind() once it is sent."""
    retire(target, "⤳ superseded by a newer message")
    gid = secrets.token_hex(6)
    now = int(time.time())
    row = []
    for label, action in actions:
        pid = secrets.token_hex(8)
        write_json(pending_dir() / (pid + ".json"), {
            "id": pid, "group": gid, "kind": kind, "action": action, "target": target,
            "profile": profile, "created": now, "message_id": None, **extra})
        row.append({"text": label, "callback_data": pid})
    write_json(groups_dir() / (gid + ".json"), {
        "gid": gid, "target": target, "kind": kind, "profile": profile,
        "message_id": None, "text": text, "created": now})
    return gid, [row]


def bind(gid: str, mid: int) -> None:
    gp = groups_dir() / (gid + ".json")
    g = read_json(gp)
    if g is None:
        return
    g["message_id"] = mid
    write_json(gp, g)
    for p in pending_dir().glob("*.json"):
        d = read_json(p)
        if d and d.get("group") == gid:
            d["message_id"] = mid
            write_json(p, d)


def send(text: str, keyboard: list | None = None, reply_to: int | None = None) -> int | None:
    c = read_conf()
    r = api("sendMessage", chat_id=c.get("TELEGRAM_CHAT"), text=clip(text),
            reply_markup={"inline_keyboard": keyboard} if keyboard else None,
            reply_to_message_id=reply_to)
    first = text.split("\n", 1)[0]
    if r.get("ok"):
        with contextlib.suppress(OSError):
            with open(NOTIFY_LOG, "a") as f:     # the line claude-notify.sh --status reads
                f.write("%s  sent via telegram: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), first))
        return r["result"]["message_id"]
    log("FAILED to send \"%s\": %s" % (first, r.get("description")))
    return None


def send_prompt_message(profile: str, pane: str, sha: str, yes: bool, more: bool,
                        title: str, body: str) -> int | None:
    actions = ([("Yes", "yes")] if yes else []) + [("No", "no")] + ([("More", "more")] if more else [])
    text = title + "\n" + body
    with locked(15):
        gid, kb = issue("prompt:" + pane, "prompt", profile, actions,
                        {"pane": pane, "prompt_sha": sha}, text)
        mid = send(text, kb)
        if mid is None:
            drop_group(gid)
            return None
        bind(gid, mid)
    return mid


def expire_old(now: float) -> None:
    for p in groups_dir().glob("*.json"):
        g = read_json(p)
        if g is None:
            p.unlink(missing_ok=True)
            continue
        if now - g.get("created", 0) > EXPIRE:
            drop_group(g["gid"])
            edit_note(g, "⌛ expired -- answer at the machine")
            log("expired %s (%s)" % (g["gid"], g.get("target")))


# --------------------------------------------------------------- inbound
def from_the_chat(chat_id, from_id) -> bool:
    """Only TELEGRAM_CHAT is obeyed. In a private chat the sender must be that
    same person; in a group chat (negative id) the chat is the boundary."""
    want = str(read_conf().get("TELEGRAM_CHAT", ""))
    if not want or str(chat_id) != want:
        return False
    return want.startswith("-") or str(from_id) == want


def answer_cb(qid: str, text: str) -> None:
    api("answerCallbackQuery", callback_query_id=qid, text=text[:190])


def pane_tail(pane: str) -> str:
    r = tmux("capture-pane", "-p", "-t", pane, "-S", "-%d" % (MORE_LINES + 200))
    lines = r.stdout.rstrip("\n").split("\n") if r.returncode == 0 else []
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines[:-25][-MORE_LINES:]) if len(lines) > 25 else ""


def handle_prompt(q: dict, d: dict) -> None:
    qid, action, pane, profile = q["id"], d["action"], d["pane"], d.get("profile", "")
    msg = q.get("message") or {}
    text = msg.get("text")
    group = read_json(groups_dir() / (d["group"] + ".json")) or {"message_id": d.get("message_id")}
    stamp = time.strftime("%H:%M")
    if knob("MUXTOPUS_NOTIFY_INBOUND", profile) == "off":
        answer_cb(qid, "the phone may not answer for this account (Settings ▸ Notifications)")
        log("refused %s on %s: inbound is off for %s" % (action, pane, profile or "personal"))
        return
    if action == "more":
        if knob("MUXTOPUS_NOTIFY_PANE_TEXT", profile) == "off":
            answer_cb(qid, "pane text is switched off")
            return
        tail = pane_tail(pane)
        send(clip(tail or "(nothing above the prompt)"), reply_to=msg.get("message_id"))
        answer_cb(qid, "sent the lines above")
        log("more: %s (%d lines)" % (pane, tail.count("\n") + 1 if tail else 0))
        return
    # THE GUARD: the prompt must STILL be on screen, and be the SAME prompt.
    r = watchdog(profile, "--prompt", pane)
    now_sha = ""
    now_yes = "0"
    for line in r.stdout.splitlines()[:2]:
        k, _, v = line.partition("\t")
        if k == "sha":
            now_sha = v
        elif k == "yes":
            now_yes = v
    if r.returncode != 0 or now_sha != d.get("prompt_sha"):
        drop_group(d["group"])
        edit_note(group, "✓ already answered at the machine (%s)" % stamp, text)
        answer_cb(qid, "already answered at the machine")
        log("stale %s on %s: prompt %s is gone (now %s)" % (action, pane, d.get("prompt_sha"), now_sha or "none"))
        return
    if action == "yes":
        if now_yes != "1":                        # never a policy, whatever the button said
            answer_cb(qid, "this prompt's first option is not a plain yes")
            log("refused yes on %s: option 1 is not a plain yes" % pane)
            return
        keys, said = ["1"], "Yes"
    elif action == "no":
        keys, said = ["Escape"], "No"
    else:
        answer_cb(qid, "unknown action")
        return
    t = tmux("send-keys", "-t", pane, *keys)
    drop_group(d["group"])
    if t.returncode != 0:
        edit_note(group, "✗ could not reach the pane (%s)" % stamp, text)
        answer_cb(qid, "the pane is gone")
        log("%s on %s FAILED: %s" % (said, pane, t.stderr.strip()))
        return
    edit_note(group, "✓ %s sent from the phone at %s" % (said, stamp), text)
    answer_cb(qid, "%s sent" % said)
    log("%s sent to %s (%s, prompt %s)" % (said, pane, profile or "personal", d.get("prompt_sha")))


def handle_callback(q: dict) -> None:
    msg = q.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    frm = (q.get("from") or {}).get("id")
    data = str(q.get("data") or "")
    if not from_the_chat(chat, frm):
        log("dropped a callback from chat %s / user %s" % (chat, frm))
        return
    if data.startswith("setup-"):
        return                                   # the setup guide's own button
    d = read_json(pending_dir() / (re.sub(r"[^0-9a-f]", "", data) + ".json")) if data else None
    if d is None:
        answer_cb(q["id"], "expired or already used")
        log("callback for an unknown id %s" % data[:20])
        return
    if time.time() - d.get("created", 0) > EXPIRE:
        g = read_json(groups_dir() / (d["group"] + ".json")) or {"message_id": d.get("message_id")}
        drop_group(d["group"])
        edit_note(g, "⌛ expired -- answer at the machine", msg.get("text"))
        answer_cb(q["id"], "expired")
        log("expired id %s pressed (%s)" % (d["id"], d.get("target")))
        return
    if d.get("kind") == "prompt":
        handle_prompt(q, d)
    elif d.get("kind") == "fork":
        answer_cb(q["id"], "answering a fork from the phone is not here yet -- use the dashboard")
        log("fork callback for %s: not yet (notify-dash phase 4)" % d.get("target"))
    else:
        answer_cb(q["id"], "unknown action")


def handle_message(m: dict) -> None:
    chat = (m.get("chat") or {}).get("id")
    frm = (m.get("from") or {}).get("id")
    if not from_the_chat(chat, frm):
        log("dropped a message from chat %s / user %s" % (chat, frm))
        return
    text = (m.get("text") or "").strip()
    log("message not acted on yet: %s" % text[:40])


def poll(profile: str = "") -> int:
    if not telegram_ready():
        return 0
    with locked(None) as got:
        if not got:
            return 0
        now = time.time()
        expire_old(now)
        try:
            offset = int((SHARED / "offset").read_text().strip() or 0)
        except (OSError, ValueError):
            offset = 0
        r = api("getUpdates", offset=offset or None, timeout=0,
                allowed_updates=["callback_query", "message"])
        if not r.get("ok"):
            log("getUpdates failed: %s" % r.get("description"))
            return 0
        for u in r.get("result", []):
            uid = int(u.get("update_id", 0))
            if uid < offset:
                continue
            # BEFORE acting: a crash between here and the keypress loses the
            # press. The other order could type into a pane twice.
            (SHARED / "offset").write_text("%d\n" % (uid + 1))
            offset = uid + 1
            log("update %d read by the %s watchdog" % (uid, profile or "personal"))
            try:
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    handle_message(u["message"])
            except Exception as e:               # one bad update must not wedge the queue
                log("update %d raised %s" % (uid, type(e).__name__))
    return 0


# ------------------------------------------------------------ questions
# §2.2: a file is answered iff some line matches ^\W*ANSWERED\b; a fork starts
# at a `## ` heading or a top-level `N.` item; a fork is answered when one of
# its lines starts `**Answer`. The tolerant minimum, until muxhandovers lands.
ANSWERED_RE = re.compile(r"^\W*ANSWERED\b", re.M)
FORK_RE = re.compile(r"^\s*(\d+\.|##\s)")
ANSWER_RE = re.compile(r"^\s*\*\*Answer")
FORK_TEXT_MAX = 1500


def fork_id(title: str) -> str:
    return hashlib.sha1(title.strip().encode()).hexdigest()[:8]


def _clean_title(line: str) -> str:
    return re.sub(r"^[#*\s]+|[*\s]+$", "", line).strip()


def forks_fallback(text: str) -> list[dict]:
    forks, cur = [], None
    for line in text.splitlines():
        if FORK_RE.match(line):
            cur = {"title": _clean_title(line), "lines": [line], "answered": False}
            forks.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
            if ANSWER_RE.match(line):
                cur["answered"] = True
    return [{"id": fork_id(f["title"]), "title": f["title"],
             "text": "\n".join(f["lines"]).strip()[:FORK_TEXT_MAX]}
            for f in forks if not f["answered"]]


def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def unanswered_forks(text: str) -> list[dict]:
    """muxhandovers.parse_forks when it exists, else the fallback above."""
    parse = getattr(muxhandovers, "parse_forks", None) if muxhandovers else None
    if parse is None:
        return forks_fallback(text)
    out = []
    for f in parse(text):
        if _get(f, "answer"):
            continue
        title = str(_get(f, "title", "") or "")
        fid = _get(f, "id")
        out.append({"id": str(fid) if fid is not None else fork_id(title), "title": title,
                    "text": str(_get(f, "text", "") or title)[:FORK_TEXT_MAX]})
    return out


def question_dirs(profile: str) -> list[tuple[pathlib.Path, bool]]:
    hdir = muxconfig.mux_dir("handovers", profile)
    legacy = pathlib.Path(muxconfig.knob(
        "MUXTOPUS_QUESTIONS_DIR", profile,
        str(muxconfig.HOME / ".code" / "theprototype-app" / "core" / "plans")))
    out = [(hdir, False)]
    if legacy.resolve() != hdir.resolve():
        out.append((legacy, True))
    return out


def unanswered_files(profile: str) -> list[dict]:
    rows = []
    for d, legacy in question_dirs(profile):
        try:
            files = sorted(d.glob("QUESTIONS-*.md"))
        except OSError:
            continue
        for p in files:
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            if ANSWERED_RE.search(text):
                continue
            title = next((_clean_title(l) for l in text.splitlines() if l.strip()), p.name)
            rows.append({"path": str(p), "slug": p.name[len("QUESTIONS-"):-len(".md")],
                         "legacy": legacy, "title": title,
                         "forks": unanswered_forks(text)})
    return rows


# ------------------------------------------------------------------ main
def _opt(rest: list[str], name: str, default: str = "") -> str:
    if name in rest:
        i = rest.index(name)
        val = rest[i + 1] if i + 1 < len(rest) else default
        del rest[i:i + 2]
        return val
    return default


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    profile = _opt(rest, "--profile")
    if cmd == "questions":
        for row in unanswered_files(profile):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if cmd == "poll":
        return poll(profile)
    if cmd == "prompt-message":
        if not telegram_ready():
            return 1
        mid = send_prompt_message(profile, _opt(rest, "--pane"), _opt(rest, "--sha"),
                                  _opt(rest, "--yes", "0") == "1", _opt(rest, "--more", "0") == "1",
                                  _opt(rest, "--title"), _opt(rest, "--body"))
        if mid is None:
            return 1
        print(mid)
        return 0
    if cmd == "retire":
        if len(rest) < 1 or not telegram_ready():
            return 1
        with locked(15):
            retire(rest[0], rest[1] if len(rest) > 1 else "✓ no longer needed")
        return 0
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
