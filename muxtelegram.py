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

try:                                    # the usage ledger, when it has collected
    import muxstats                     # type: ignore  # noqa: E402
except ImportError:                     # pragma: no cover - depends on the tree
    muxstats = None

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


_HOLDING = False


@contextlib.contextmanager
def locked(wait: float | None):
    """The one-poller lock. wait=None: do not wait at all (yield False when it
    is held). Otherwise wait up to that many seconds, then carry on unlocked
    rather than lose a message. Re-entrant within this process: a command
    handled under poll's lock re-issues prompts without deadlocking on it."""
    global _HOLDING
    if _HOLDING:
        yield True
        return
    SHARED.mkdir(parents=True, exist_ok=True)
    f = open(SHARED / "lock", "w")
    got = False
    try:
        deadline = time.time() + (wait or 0)
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = _HOLDING = True
                break
            except OSError:
                if wait is None or time.time() >= deadline:
                    break
                time.sleep(0.1)
        yield got
    finally:
        if got:
            _HOLDING = False
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
                        title: str, body: str, push: bool = True) -> int | None:
    """push=True is the watchdog telling; a /mute holds it back. A pull
    (/pending, /windows) is somebody asking, and is never muted."""
    if push and muted_until() > time.time():
        log("muted: %s" % title)
        return None
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
            if g.get("kind") != "cmd":          # a /status keyboard just stops working
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
    if time.time() - d.get("created", 0) > EXPIRE and d.get("kind") == "cmd":
        drop_group(d["group"])
        answer_cb(q["id"], "expired -- send /status again")
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
    elif d.get("kind") == "cmd":
        handle_cmd_button(q, d)
    elif d.get("kind") == "fork":
        answer_cb(q["id"], "answering a fork from the phone is not here yet -- use the dashboard")
        log("fork callback for %s: not yet (notify-dash phase 4)" % d.get("target"))
    else:
        answer_cb(q["id"], "unknown action")


def handle_message(m: dict, profile: str = "") -> None:
    chat = (m.get("chat") or {}).get("id")
    frm = (m.get("from") or {}).get("id")
    if not from_the_chat(chat, frm):
        log("dropped a message from chat %s / user %s" % (chat, frm))
        return
    text = (m.get("text") or "").strip()
    if text.startswith("/"):
        handle_command(text, profile)
        return
    log("a typed message is not acted on yet (fork replies: notify-dash phase 4): %s" % text[:40])


def poll(profile: str = "") -> int:
    if not telegram_ready():
        return 0
    with locked(None) as got:
        if not got:
            return 0
        now = time.time()
        register_commands()
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
                    handle_message(u["message"], profile)
            except Exception as e:               # one bad update must not wedge the queue
                log("update %d raised %s" % (uid, type(e).__name__))
    return 0


# ------------------------------------------------------------------ pull
# §3b. EVERY SWITCH MAY BE OFF and the phone can still find out and act: a push
# can be missed, muted or dismissed, and a dismissed message takes its buttons
# with it. Everything is read from what the watchdogs already publish, for
# every account on this machine.
COMMANDS = [
    ("status", "every account at a glance"),
    ("pending", "everything that needs you, with fresh buttons"),
    ("questions", "unanswered question files"),
    ("blocked", "schedule entries that are not launching, and why"),
    ("windows", "one line per session"),
    ("stats", "what the ledger says: tokens, cost, sessions"),
    ("mute", "pushes off for a while, e.g. /mute 2h"),
    ("unmute", "pushes back on"),
    ("help", "what this bot answers"),
]
HELP = """/status -- per account: sessions by state, budget, schedule, handovers, questions, heartbeat
/pending -- everything that needs you, RE-ISSUED with fresh buttons (old ones stop working)
/questions -- unanswered QUESTIONS files
/blocked -- each entry that is not launching, with the scheduler's why
/windows -- one line per session; a needs-you row brings its buttons
/stats -- the usage ledger's totals; the buttons switch week / month / all
/mute 2h -- pushes off for a while (30m, 2h, 1d); asking keeps working
/unmute -- pushes back on
Replies come within one watchdog pass (at most ~30 s)."""
STATUS_COLS = ("sid", "name", "pane", "ver", "ctx", "state", "reset", "action", "resumed",
               "spent", "cached", "optout", "model", "idle", "job", "cwd", "wound", "moptout", "pid")
STATE_WORDS = (("working", "working"), ("waiting", "needs you"), ("idle", "idle"),
               ("limited", "limited"), ("due", "due"), ("stranded", "stranded"))


def register_commands(force: bool = False):
    """setMyCommands, only when the list differs from what was last registered
    -- so it appears in Telegram's own menu button without a call per pass."""
    sha = hashlib.sha1(json.dumps(COMMANDS).encode()).hexdigest()
    stamp = SHARED / "commands.sha"
    try:
        if not force and stamp.read_text().strip() == sha:
            return None
    except OSError:
        pass
    r = api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
    if not r.get("ok"):
        log("setMyCommands failed: %s" % r.get("description"))
        return False
    SHARED.mkdir(parents=True, exist_ok=True)
    stamp.write_text(sha + "\n")
    log("registered %d commands" % len(COMMANDS))
    return True


def muted_until() -> float:
    try:
        return float((SHARED / "mute").read_text().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def profiles() -> list[str]:
    """Every account on this machine, as profile.sh's mux_profiles finds them:
    ~/.claude is the default, ~/.claude-<name> a named one."""
    home = pathlib.Path.home()
    out = [""] if (home / ".claude").is_dir() else []
    for d in sorted(home.glob(".claude-*")):
        name = d.name[len(".claude-"):]
        if not d.is_dir() or d.name.endswith((".bak", "~", ".old", ".tmp")):
            continue
        if re.fullmatch(r"[A-Za-z0-9_-]+", name):
            out.append(name)
    return out


def label(profile: str) -> str:
    return profile or "personal"


def wd_dir(profile: str) -> pathlib.Path:
    return STATE_HOME / ("claude-watchdog" + muxconfig.suffix_of(profile))


def tsv(path: pathlib.Path) -> list[list[str]]:
    try:
        return [l.split("\t") for l in path.read_text().splitlines() if l.strip()]
    except OSError:
        return []


def sessions(profile: str) -> list[dict]:
    out = []
    for row in tsv(wd_dir(profile) / "status.tsv"):
        s = dict(zip(STATUS_COLS, row))
        pid = s.get("pid", "")
        if pid.isdigit() and not pathlib.Path("/proc", pid).exists():
            continue                             # the window closed since the pass
        out.append(s)
    return out


def verdicts(profile: str) -> list[dict]:
    return [dict(zip(("file", "verdict", "why", "when"), r)) for r in tsv(wd_dir(profile) / "sched-why.tsv")]


def long_blocked(profile: str) -> list[dict]:
    after = knob("MUXTOPUS_NOTIFY_BLOCKED_AFTER", profile)
    mins = int(after) if after.isdigit() else 120
    if mins <= 0:
        return []
    since = {r[0]: r[1] for r in tsv(wd_dir(profile) / "notify" / "blocked.tsv") if len(r) > 1}
    now = time.time()
    return [v for v in verdicts(profile) if v["verdict"] == "blocked"
            and since.get(v["file"], "").isdigit() and now - int(since[v["file"]]) >= mins * 60]


def human_age(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm" % (sec // 60)
    if sec < 172800:
        return "%dh" % (sec // 3600)
    return "%dd" % (sec // 86400)


def status_counts(profile: str) -> dict:
    ss = sessions(profile)
    vs = verdicts(profile)
    return {
        "states": {k: sum(1 for s in ss if s.get("state") == k) for k, _ in STATE_WORDS},
        "sessions": len(ss),
        "pending": len(vs),
        "blocked": sum(1 for v in vs if v["verdict"] == "blocked"),
        "stalled": sum(1 for v in vs if v["verdict"] == "stalled"),
        "questions": len(unanswered_files(profile)),
    }


def status_text(profile: str) -> tuple[str, dict]:
    c = status_counts(profile)
    st = " · ".join("%d %s" % (c["states"][k], w) for k, w in STATE_WORDS if c["states"][k])
    lines = ["%s · status" % label(profile),
             "sessions: %s" % (st or "none")]
    u = {r[0]: r[1] for r in tsv(wd_dir(profile) / "usage.tsv") if len(r) > 1}
    if u:
        reset = u.get("session_reset_at", "")
        at = time.strftime("%H:%M", time.localtime(int(reset))) if reset.isdigit() else u.get("session_reset", "?")
        age = human_age(time.time() - int(u["at"])) + " ago" if u.get("at", "").isdigit() else "?"
        lines.append("budget: session %s%% · week %s%% · resets %s (read %s)"
                     % (u.get("session_pct", "?"), u.get("week_pct", "?"), at, age))
    lines.append("schedule: %d pending · %d blocked · %d stalled" % (c["pending"], c["blocked"], c["stalled"]))
    try:
        opened = len(list(muxconfig.mux_dir("handovers", profile).glob("STATUS-*.md")))
    except OSError:
        opened = 0
    lines.append("handovers: %d open · questions: %d unanswered" % (opened, c["questions"]))
    hb = tsv(wd_dir(profile) / "heartbeat")
    if hb and hb[0][0].isdigit():
        lines.append("watchdog: scanned %s ago" % human_age(time.time() - int(hb[0][0])))
    else:
        lines.append("watchdog: no heartbeat -- not running?")
    if muted_until() > time.time():
        lines.append("pushes muted until %s" % time.strftime("%H:%M", time.localtime(muted_until())))
    return "\n".join(lines), c


def cmd_keyboard(profile: str, c: dict) -> tuple[str, list]:
    return issue("cmd:" + secrets.token_hex(4), "cmd", profile, [
        ("Needs you (%d)" % c["states"]["waiting"], "needs"),
        ("Questions (%d)" % c["questions"], "questions"),
        ("Blocked (%d)" % c["blocked"], "blocked"),
        ("Refresh", "refresh")], {}, "")


def cmd_status(profiles_: list[str], note: str = "") -> None:
    for p in profiles_:
        text, c = status_text(p)
        gid, kb = cmd_keyboard(p, c)
        mid = send(text + note, kb)
        note = ""
        if mid is None:
            drop_group(gid)
        else:
            bind(gid, mid)


def reissue_prompt(profile: str, s: dict) -> bool:
    """A needs-you session's prompt, sent again with NEW ids; the old message
    is superseded. The only tmux fork a command costs."""
    pane = s.get("pane", "")
    r = watchdog(profile, "--prompt", pane)
    if r.returncode != 0:
        return False
    head, box = {}, []
    for i, line in enumerate(r.stdout.rstrip("\n").split("\n")):
        k, _, v = line.partition("\t")
        if i < 3 and k in ("sha", "yes", "question"):
            head[k] = v
        else:
            box.append(line)
    body = "at a prompt: %s" % head.get("question", "")
    pane_text = knob("MUXTOPUS_NOTIFY_PANE_TEXT", profile) != "off"
    if pane_text:
        body += "\n\n" + "\n".join(box)
    return send_prompt_message(profile, pane, head.get("sha", ""), head.get("yes") == "1", pane_text,
                               "%s · needs you: %s" % (label(profile), s.get("name", pane)),
                               body, push=False) is not None


def cmd_pending(profiles_: list[str], note: str = "", only: str = "") -> None:
    said = 0
    for p in profiles_:
        if only in ("", "needs"):
            for s in sessions(p):
                if s.get("state") == "waiting" and reissue_prompt(p, s):
                    said += 1
        if only:
            continue
        files = unanswered_files(p)
        if files:
            n = sum(len(f["forks"]) for f in files)
            send("%s · questions\n%d unanswered fork(s) in %d file(s). Answering a fork from the phone: "
                 "not yet -- open the dashboard.%s" % (label(p), n, len(files), note))
            note = ""
            said += 1
        items = ["stalled: %s -- %s" % (v["file"], v["why"]) for v in verdicts(p) if v["verdict"] == "stalled"]
        items += ["blocked: %s -- %s" % (v["file"], v["why"]) for v in long_blocked(p)]
        items += ["stranded: %s" % s.get("name") for s in sessions(p) if s.get("state") == "stranded"]
        if items:
            send("%s · trouble\n%s%s" % (label(p), "\n".join(items), note))
            note = ""
            said += 1
    if not said:
        send("nothing needs you" + note)


def cmd_questions(profiles_: list[str], note: str = "") -> None:
    lines = []
    for p in profiles_:
        for f in unanswered_files(p):
            lines.append("%s · %s · %d fork(s)%s" % (label(p), f["slug"], len(f["forks"]),
                                                     " (legacy folder)" if f["legacy"] else ""))
    if not lines:
        send("no unanswered questions" + note)
        return
    send("unanswered QUESTIONS files:\n%s\n\nChoosing one to answer from the phone: not yet -- "
         "open the dashboard.%s" % ("\n".join(lines), note))


def cmd_blocked(profiles_: list[str], note: str = "") -> None:
    lines = []
    for p in profiles_:
        for v in verdicts(p):
            if v["verdict"] != "due":
                lines.append("%s · %s · %s\n  %s" % (label(p), v["file"], v["verdict"], v["why"]))
    send(("not launching:\n" + "\n".join(lines) if lines else "nothing is held") + note)


def cmd_windows(profiles_: list[str], note: str = "") -> None:
    cw = 0
    lines, waiting = [], []
    for p in profiles_:
        try:
            cw = int(knob("CLAUDE_CONTEXT_WINDOW", p) or 0)
        except ValueError:
            cw = 0
        for s in sessions(p):
            idle = s.get("idle", "-1")
            ctx = int(s["ctx"]) if s.get("ctx", "").isdigit() else 0
            word = dict(STATE_WORDS).get(s.get("state", ""), s.get("state", ""))
            lines.append("%s · %s · %s%s · ctx %d%%" % (
                label(p), s.get("name"), word,
                (" %s" % human_age(int(idle))) if idle.lstrip("-").isdigit() and int(idle) >= 0 else "",
                ctx * 100 // cw if cw else 0))
            if s.get("state") == "waiting":
                waiting.append((p, s))
    send(("\n".join(lines) if lines else "no sessions") + note)
    for p, s in waiting:
        reissue_prompt(p, s)


# ------------------------------------------------------------------ stats
# plan-insights.md §4: the same module, a third face. The VIEW and the CLI may
# collect first; this one never does -- a command must cost no more than
# reading what the watchdog's own five-minute hook already wrote, and a
# ledger one pass out of date is not worth a fork on somebody's phone.
STATS_PERIODS = ("week", "month", "all")


def stats_report(profile: str, period: str):
    """One account's ledger as muxstats reports it, or None with the reason."""
    if muxstats is None:
        return None, "muxstats is not in this checkout"
    try:
        led = muxstats.load(muxstats.stats_dir(profile))
    except Exception as exc:                     # noqa: BLE001 - a report is optional
        return None, "cannot read the ledger: %s" % exc
    if not led.rows:
        return None, ("nothing collected yet -- the watchdog writes the ledger "
                      "every five minutes once a session has run")
    table = muxstats.prices(muxstats.prices_path())
    try:
        rep = muxstats.query(led, period, {}, "project", None, table)
    except Exception as exc:                     # noqa: BLE001
        return None, "cannot read the ledger: %s" % exc
    return rep, ""


def stats_text(profile: str, period: str) -> str:
    """The headline figures, not the eight-row report: a phone screen holds
    about five lines before it is scrolled past. Every number here is one
    `muxtopus stats --json` prints for the same period."""
    rep, why = stats_report(profile, period)
    if rep is None:
        return "%s · stats\n%s" % (label(profile), why)
    t, k, s = rep["tokens"], rep["cost"], rep["sessions"]
    p = rep["period"]
    lines = ["%s · stats · %s (%s – %s)" % (label(profile), p["label"], p["start"], p["end"]),
             "%s tokens · %d session(s)" % (muxstats.human_tokens(t["total"]), s["count"])]
    if k["usd"] is None:
        lines.append("no prices -- tokens only")
    else:
        lines.append("%s API-equivalent · %s / day" % (muxstats._usd(k["usd"]),
                                                       muxstats._usd(k["per_day"])))
    lines.append("in %s · out %s · %s of input from cache"
                 % (muxstats.human_tokens(t["input"]), muxstats.human_tokens(t["output"]),
                    muxstats._pct(rep["cache"]["read_share"])))
    top = [b for b in rep["breakdown"] if b["key"]][:3]
    if top:
        lines.append("top: " + " · ".join(
            "%s %s" % (b["key"].rstrip("/").rsplit("/", 1)[-1], muxstats.human_tokens(b["tokens"]))
            for b in top))
    return "\n".join(lines)


def stats_keyboard(profile: str, period: str) -> tuple[str, list]:
    """week · month · all, the one in view marked. A new group every time, so
    an old message's buttons retire rather than answering with a period its
    own text does not show."""
    return issue("cmd:" + secrets.token_hex(4), "cmd", profile,
                 [(("· %s ·" % q) if q == period else q, "stats-" + q)
                  for q in STATS_PERIODS], {"period": period}, "")


def cmd_stats(profiles_: list[str], period: str = "week", note: str = "") -> None:
    for p in profiles_:
        text = stats_text(p, period)
        gid, kb = stats_keyboard(p, period)
        mid = send(text + note, kb)
        note = ""
        if mid is None:
            drop_group(gid)
        else:
            bind(gid, mid)


def parse_duration(arg: str) -> int | None:
    m = re.fullmatch(r"\s*(\d+)\s*([mhd]?)\s*", arg or "1h")
    if not m:
        return None
    return int(m.group(1)) * {"": 60, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def handle_command(text: str, profile: str) -> None:
    word, _, arg = text.partition(" ")
    cmd = word[1:].split("@", 1)[0].lower()
    now = time.time()
    # THE FIRST COMMAND OF A BURST says how long replies take, once.
    note = ""
    try:
        last = float((SHARED / "last_command").read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    if now - last > 600:
        note = "\n\n(replies come within one watchdog pass, at most ~30 s)"
    (SHARED / "last_command").write_text("%d\n" % now)
    ps = profiles() or [profile]
    log("command /%s" % cmd)
    if cmd in ("status", "start"):
        cmd_status(ps, note)
    elif cmd == "pending":
        cmd_pending(ps, note)
    elif cmd == "questions":
        cmd_questions(ps, note)
    elif cmd == "blocked":
        cmd_blocked(ps, note)
    elif cmd == "windows":
        cmd_windows(ps, note)
    elif cmd == "stats":
        word = (arg or "week").strip().lower()
        cmd_stats(ps, word if word in STATS_PERIODS else "week", note)
    elif cmd == "mute":
        sec = parse_duration(arg)
        if sec is None:
            send("say how long: /mute 30m, /mute 2h, /mute 1d" + note)
            return
        until = now + sec
        (SHARED / "mute").write_text("%d\n" % until)
        send("pushes muted until %s -- /status, /pending and the rest still answer%s"
             % (time.strftime("%a %H:%M", time.localtime(until)), note))
    elif cmd == "unmute":
        (SHARED / "mute").unlink(missing_ok=True)
        send("pushes are back on" + note)
    elif cmd == "help":
        send(HELP)
    else:
        send("unknown command /%s -- /help lists them" % cmd)


def handle_cmd_button(q: dict, d: dict) -> None:
    """The /status keyboard. Not consumed by a press: it is a way to ask."""
    p, action = d.get("profile", ""), d.get("action")
    msg = q.get("message") or {}
    answer_cb(q["id"], "on its way")
    log("status button %s (%s)" % (action, label(p)))
    if action == "needs":
        if not any(s.get("state") == "waiting" for s in sessions(p)):
            send("%s: nothing is at a prompt" % label(p))
        else:
            cmd_pending([p], only="needs")
    elif action == "questions":
        cmd_questions([p])
    elif action == "blocked":
        cmd_blocked([p])
    elif action.startswith("stats-"):
        period = action[len("stats-"):]
        gid, kb = stats_keyboard(p, period)
        r = api("editMessageText", chat_id=read_conf().get("TELEGRAM_CHAT"),
                message_id=msg.get("message_id"), text=clip(stats_text(p, period)),
                reply_markup={"inline_keyboard": kb})
        drop_group(d["group"])
        bind(gid, msg.get("message_id"))
        if not r.get("ok"):
            log("stats edit failed: %s" % r.get("description"))
    elif action == "refresh":
        text, c = status_text(p)
        gid, kb = cmd_keyboard(p, c)
        r = api("editMessageText", chat_id=read_conf().get("TELEGRAM_CHAT"),
                message_id=msg.get("message_id"), text=clip(text), reply_markup={"inline_keyboard": kb})
        drop_group(d["group"])
        bind(gid, msg.get("message_id"))
        if not r.get("ok"):
            log("refresh edit failed: %s" % r.get("description"))


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
    if cmd == "commands":                   # --setup registers the bot's menu
        if not telegram_ready():
            return 1
        return 0 if register_commands(force="--force" in rest) is not False else 1
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
