#!/usr/bin/env python3
"""muxstats -- a ledger of what was used, counted once, that outlives the
transcripts it was read from.

    python3 muxstats.py collect [--profile P]    read what is new, update the ledger

COUNTS ONLY. No prompt, no reply, no tool input, no file name other than the
project directory is ever written by this module. The ledger holds numbers,
model ids, tool NAMES, session ids and the working directory of a session;
the dedupe index holds truncated hashes. That is what a public release has to
be able to promise, and every writer below is a numeric aggregate.

WHY A LEDGER. Claude Code deletes a transcript after `cleanupPeriodDays` (30 by
default), so "everything to date" only exists if something keeps its own
record. This is that record, one per account:

    $XDG_STATE_HOME/muxtopus/stats[-<profile>]/
      ledger.tsv    one row per (day, session, model, side) -- LEDGER_COLS
      offsets.tsv   per transcript: inode, size, byte offset, session, model
      seen/YYYY-MM.tsv   hash of each counted message key -> the file that owns it
      limits.tsv    one row per usage limit hit: type, resets_at, first, last
      meta          schema, collecting-since, last collect, backfill

MEASURED, and the reason for the dedupe index (plan-insights §0.2): one API
message is written as one line PER CONTENT BLOCK, each repeating the same
`usage`, so a naive sum over lines is wrong by more than 2x. And a resumed
session COPIES earlier messages into its new file -- same message id, same
request id, same timestamp, a different sessionId. So a message is counted
once, keyed by (message.id, requestId), by whichever file claimed it first;
the key's day is the record's own timestamp, which the copy keeps, so the
index only ever has to be consulted for one month.

INCREMENTAL AND IDEMPOTENT. A transcript is read from its stored offset up to
its last complete line (a line being written right now is left for the next
collect). A transcript that SHRANK or changed inode resets its whole session:
its rows, its index entries and the offsets of every file of that session are
dropped and re-read from 0, so the day-rows are replaced rather than added.
Every file is rewritten whole through `.tmp` + os.replace. Running collect
twice changes nothing; tests/test_stats.py proves it byte for byte.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import hashlib
import json
import os
import pathlib
import sys

SCHEMA = 1

# The ledger's columns, in file order. `ctx` of a request is input +
# cache_read + cache_creation: what the model actually saw. `active_s` is the
# sum of turn_duration, so a window left open for three days is not a
# three-day session. `tool_mix` is "Name=count;..." sorted by name -- tool
# NAMES only, never their input. A `coarse` row is a day backfilled from
# Claude Code's own stats-cache.json: its single total is in `in`, everything
# else is 0, and it counts toward totals only.
LEDGER_COLS = (
    "day", "session", "project", "lane", "model", "side",
    "requests", "in", "out", "cache_read", "cache_w5m", "cache_w1h", "thinking",
    "ctx_peak", "ctx_sum", "ctx_n", "tools", "web", "turns", "active_s",
    "compactions", "first_ts", "last_ts", "tool_mix", "coarse",
)
TEXT_COLS = ("day", "session", "project", "lane", "model", "tool_mix")
INT_COLS = tuple(c for c in LEDGER_COLS if c not in TEXT_COLS)
ROW_KEY = ("day", "session", "model", "side")

OFFSET_COLS = ("file", "inode", "size", "offset", "session", "model")
LIMIT_COLS = ("type", "resets_at", "first_ts", "last_ts")


# ---------------------------------------------------------------- paths
def _xdg_state() -> pathlib.Path:
    return pathlib.Path(os.environ.get("XDG_STATE_HOME")
                        or str(pathlib.Path.home() / ".local" / "state"))


def _suffix(profile: str) -> str:
    return ("-" + profile) if profile else ""


def stats_dir(profile: str = "") -> pathlib.Path:
    return _xdg_state() / "muxtopus" / ("stats" + _suffix(profile))


def watchdog_dir(profile: str = "") -> pathlib.Path:
    return _xdg_state() / ("claude-watchdog" + _suffix(profile))


def config_dir_of(profile: str = "") -> pathlib.Path:
    """The account's Claude config dir: the same rule profile.sh applies.
    CLAUDE_CONFIG_DIR wins only when no profile was named."""
    if not profile and os.environ.get("CLAUDE_CONFIG_DIR"):
        return pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"])
    return pathlib.Path.home() / (".claude" + _suffix(profile))


def profile_of(config_dir: str | os.PathLike | None = None) -> str:
    """~/.claude -> "", ~/.claude-work -> "work" (muxconfig.profile_of)."""
    d = str(config_dir or os.environ.get("CLAUDE_CONFIG_DIR")
            or pathlib.Path.home() / ".claude")
    name = pathlib.Path(d).name
    if name.startswith(".claude"):
        name = name[len(".claude"):]
    return name.lstrip("-_")


# ------------------------------------------------------------ small I/O
def _write_atomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _read_tsv(path: pathlib.Path, cols: tuple) -> list[dict]:
    """Rows of a headed TSV. A missing file is no rows; a short row is padded
    rather than refused, so a hand-trimmed file still loads."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[1:]:
        if not line:
            continue
        f = line.split("\t")
        f += [""] * (len(cols) - len(f))
        out.append(dict(zip(cols, f)))
    return out


def _tsv(rows: list[dict], cols: tuple) -> str:
    out = ["\t".join(cols)]
    for r in rows:
        out.append("\t".join(str(r.get(c, "")) for c in cols))
    return "\n".join(out) + "\n"


def _clean(s) -> str:
    """A text field can never break a row."""
    return str(s or "").replace("\t", " ").replace("\n", " ")


def _h(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _epoch(ts) -> int | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return int(_dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def local_day(epoch: int) -> str:
    """The LOCAL calendar day of an instant -- a day is the user's day."""
    return _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def _home_abbrev(p: str) -> str:
    home = str(pathlib.Path.home())
    if p == home:
        return "~"
    if p.startswith(home + "/"):
        return "~" + p[len(home):]
    return p


# ----------------------------------------------------------------- rows
def new_row(day: str, session: str, model: str, side: int) -> dict:
    r = {c: 0 for c in INT_COLS}
    r.update(day=day, session=session, project="", lane="", model=model,
             side=side, tool_mix="")
    return r


def _row_from_tsv(d: dict) -> dict:
    r = dict(d)
    for c in INT_COLS:
        try:
            r[c] = int(r.get(c) or 0)
        except ValueError:
            r[c] = 0
    return r


def _mix_parse(s: str) -> dict:
    out = {}
    for part in (s or "").split(";"):
        name, _, n = part.rpartition("=")
        if name:
            out[name] = out.get(name, 0) + int(n or 0)
    return out


def _mix_str(d: dict) -> str:
    return ";".join("%s=%d" % (k, d[k]) for k in sorted(d))


def load_ledger(state_dir) -> list[dict]:
    return [_row_from_tsv(d) for d in _read_tsv(pathlib.Path(state_dir) / "ledger.tsv", LEDGER_COLS)]


def load_meta(state_dir) -> dict:
    out = {}
    try:
        for line in (pathlib.Path(state_dir) / "meta").read_text().splitlines():
            k, _, v = line.partition("\t")
            if k:
                out[k] = v
    except OSError:
        pass
    return out


# --------------------------------------------------------------- lanes
def lane_map(wd_dir) -> dict:
    """sessionId -> tree slug, joined through the pane: status.tsv says which
    pane a session is in NOW, tree.tsv which slug the scheduler opened in that
    pane. Pane ids restart with the tmux server, so the latest launch wins."""
    if not wd_dir:
        return {}
    wd = pathlib.Path(wd_dir)
    pane_slug = {}
    try:
        tree = (wd / "tree.tsv").read_text().splitlines()
    except OSError:
        tree = []
    best = {}
    for line in tree:
        f = line.split("\t")
        if len(f) < 5 or not f[3].startswith("%"):
            continue
        try:
            at = int(f[4])
        except ValueError:
            at = 0
        if f[3] not in best or at >= best[f[3]]:
            best[f[3]] = at
            pane_slug[f[3]] = f[0]
    out = {}
    try:
        status = (wd / "status.tsv").read_text().splitlines()
    except OSError:
        status = []
    for line in status:
        f = line.split("\t")
        if len(f) >= 3 and f[2] in pane_slug and f[0] != "SESSION":
            out[f[0]] = pane_slug[f[2]]
    return out


# ------------------------------------------------------------- collect
@dataclasses.dataclass
class CollectReport:
    files: int = 0            # transcripts seen
    files_read: int = 0       # ...that had new bytes
    bytes_read: int = 0
    requests: int = 0         # messages counted for the first time
    duplicate_lines: int = 0  # further block lines of a message already counted
    copies: int = 0           # messages another file (a resumed session) owns
    bad_lines: int = 0        # not JSON, or not an object
    sessions_reset: int = 0   # shrunk or re-inoded -> re-read from 0
    coarse_days: int = 0      # rows backfilled from stats-cache.json
    rows: int = 0

    def line(self) -> str:
        return ("collect: %d file(s), %d read (%d KB), %d request(s) new, "
                "%d duplicate block line(s), %d resumed cop(ies), %d bad line(s), "
                "%d session(s) reset, %d coarse row(s), %d ledger row(s)" % (
                    self.files, self.files_read, self.bytes_read // 1024,
                    self.requests, self.duplicate_lines, self.copies,
                    self.bad_lines, self.sessions_reset, self.coarse_days,
                    self.rows))


class _Seen:
    """The dedupe index: key hash -> id of the file that counted it, one file
    per month, loaded lazily and written back only when it changed."""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.months: dict[str, dict] = {}
        self.dirty: set[str] = set()

    def _m(self, month: str) -> dict:
        if month not in self.months:
            d = {}
            try:
                for line in (self.root / (month + ".tsv")).read_text().splitlines():
                    k, _, owner = line.partition("\t")
                    if k:
                        d[k] = owner
            except OSError:
                pass
            self.months[month] = d
        return self.months[month]

    def owner(self, day: str, key: str) -> str | None:
        return self._m(day[:7]).get(key)

    def claim(self, day: str, key: str, fid: str) -> None:
        self._m(day[:7])[key] = fid
        self.dirty.add(day[:7])

    def drop_owners(self, fids: set) -> None:
        if not fids:
            return
        try:
            names = sorted(p.stem for p in self.root.glob("*.tsv"))
        except OSError:
            names = []
        for month in set(names) | set(self.months):
            d = self._m(month)
            gone = [k for k, o in d.items() if o in fids]
            for k in gone:
                del d[k]
            if gone:
                self.dirty.add(month)

    def save(self) -> None:
        for month in sorted(self.dirty):
            d = self.months[month]
            _write_atomic(self.root / (month + ".tsv"),
                          "".join("%s\t%s\n" % (k, d[k]) for k in sorted(d)))
        self.dirty.clear()


def _transcripts(projects: pathlib.Path) -> list[pathlib.Path]:
    try:
        return sorted(p for p in projects.rglob("*.jsonl") if p.is_file())
    except OSError:
        return []


def _file_session(rel: pathlib.Path) -> tuple[str, int]:
    """(session id, is-subagent) from a transcript's place in projects/:
    <proj>/<sid>.jsonl, or <proj>/<sid>/subagents/agent-*.jsonl."""
    parts = rel.parts
    if "subagents" in parts:
        i = parts.index("subagents")
        return (parts[i - 1] if i > 0 else rel.stem), 1
    return rel.stem, 0


def collect(config_dir, state_dir, now: int | None = None, *, wd_dir=None,
            stats_cache=None) -> CollectReport:
    """Read every transcript's new bytes into the ledger. See the module
    docstring for what is kept and why it is counted the way it is."""
    config_dir = pathlib.Path(config_dir)
    state = pathlib.Path(state_dir)
    now = int(now if now is not None else _dt.datetime.now().timestamp())
    projects = config_dir / "projects"
    rep = CollectReport()

    rows = {tuple(r[k] for k in ROW_KEY): r for r in load_ledger(state)}
    offsets = {d["file"]: d for d in _read_tsv(state / "offsets.tsv", OFFSET_COLS)}
    limits = {(d["type"], d["resets_at"]): d for d in _read_tsv(state / "limits.tsv", LIMIT_COLS)}
    seen = _Seen(state / "seen")
    meta = load_meta(state)

    lanes = {}
    for r in rows.values():
        if r["lane"]:
            lanes.setdefault(r["session"], r["lane"])
    for sid, slug in lane_map(wd_dir).items():
        lanes.setdefault(sid, slug)

    files = _transcripts(projects)
    rep.files = len(files)
    stat = {}
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        stat[p.relative_to(projects).as_posix()] = (p, st.st_ino, st.st_size, st.st_mtime)

    # A file that shrank or was replaced resets its whole SESSION: subagent
    # files share one (session, side) row, so no smaller unit can be
    # subtracted exactly. Rows of that session go, the index forgets the
    # session's files, and every file of it is read again from 0.
    reset_sessions = set()
    for rel, (p, ino, size, _) in stat.items():
        o = offsets.get(rel)
        if o and (str(ino) != o["inode"] or size < int(o["offset"] or 0)):
            reset_sessions.add(_file_session(pathlib.PurePosixPath(rel))[0])
    if reset_sessions:
        rep.sessions_reset = len(reset_sessions)
        fids = set()
        for rel in list(offsets) + list(stat):
            if _file_session(pathlib.PurePosixPath(rel))[0] in reset_sessions:
                fids.add(_h(rel))
                offsets.pop(rel, None)
        seen.drop_owners(fids)
        for k in [k for k, r in rows.items() if r["session"] in reset_sessions]:
            del rows[k]

    # Oldest first, so a message a resumed session copied is claimed by the
    # session that actually sent it -- the totals are right either way.
    for rel in sorted(stat, key=lambda k: (stat[k][3], k)):
        p, ino, size, _ = stat[rel]
        o = offsets.get(rel) or {}
        off = int(o.get("offset") or 0)
        fsid, fside = _file_session(pathlib.PurePosixPath(rel))
        model = o.get("model") or ""
        if size > off:
            try:
                with open(p, "rb") as fh:
                    fh.seek(off)
                    data = fh.read(size - off)
            except OSError:
                continue
            cut = data.rfind(b"\n")
            if cut >= 0:
                rep.files_read += 1
                rep.bytes_read += cut + 1
                model = _ingest(data[:cut + 1], _h(rel), fsid, fside, model,
                                rows, seen, limits, lanes, rep)
                off += cut + 1
        offsets[rel] = {"file": rel, "inode": ino, "size": size, "offset": off,
                        "session": fsid, "model": model}
    # A transcript Claude Code deleted keeps its rows; its offset is dropped.
    for rel in [r for r in offsets if r not in stat]:
        del offsets[rel]

    for r in rows.values():
        if not r["lane"] and r["session"] in lanes and not r["coarse"]:
            r["lane"] = lanes[r["session"]]

    # COARSE BACKFILL, once: Claude Code's stats-cache.json for the days older
    # than the oldest surviving transcript. Daily tokens by model and nothing
    # else, flagged, so a figure needing more than a total can skip it.
    if meta.get("backfill") != "done":
        sc = pathlib.Path(stats_cache) if stats_cache else config_dir / "stats-cache.json"
        real_days = [r["day"] for r in rows.values() if not r["coarse"]]
        oldest = min(real_days) if real_days else None
        try:
            daily = json.loads(sc.read_text()).get("dailyModelTokens") or []
        except (OSError, ValueError, AttributeError):
            daily = []
        for d in daily if isinstance(daily, list) else []:
            day = d.get("date") if isinstance(d, dict) else None
            if not isinstance(day, str) or (oldest and day >= oldest):
                continue
            for m, n in (d.get("tokensByModel") or {}).items():
                if not isinstance(n, int) or n <= 0:
                    continue
                r = rows.setdefault((day, "-", _clean(m), 0), new_row(day, "-", _clean(m), 0))
                r.update(project="-", coarse=1, **{"in": n})
                rep.coarse_days += 1
        meta["backfill"] = "done"

    ledger = sorted(rows.values(), key=lambda r: (r["day"], r["session"], r["model"], r["side"]))
    rep.rows = len(ledger)
    since = min((r["day"] for r in ledger), default="")
    meta["schema"] = str(SCHEMA)
    if since and (not meta.get("since") or since < meta["since"]):
        meta["since"] = since
    meta.setdefault("since", local_day(now))
    meta["last_collect"] = str(now)

    seen.save()
    _write_if_changed(state / "ledger.tsv", _tsv(ledger, LEDGER_COLS))
    _write_if_changed(state / "offsets.tsv",
                      _tsv([offsets[k] for k in sorted(offsets)], OFFSET_COLS))
    _write_if_changed(state / "limits.tsv",
                      _tsv([limits[k] for k in sorted(limits)], LIMIT_COLS))
    _write_atomic(state / "meta", "".join("%s\t%s\n" % (k, meta[k]) for k in sorted(meta)))
    return rep


def _write_if_changed(path: pathlib.Path, text: str) -> None:
    try:
        if path.read_text() == text:
            return
    except OSError:
        pass
    _write_atomic(path, text)


def _num(d, k) -> int:
    v = d.get(k) if isinstance(d, dict) else None
    return v if isinstance(v, int) and v > 0 else 0


def _ingest(data: bytes, fid: str, fsid: str, fside: int, model: str,
            rows: dict, seen: _Seen, limits: dict, lanes: dict,
            rep: CollectReport) -> str:
    """Fold complete lines into the rows. Returns the model last seen, which
    is what a turn record (it names none) is attributed to next time."""

    def row(day, sid, mdl, side, cwd):
        k = (day, sid, mdl, side)
        r = rows.get(k)
        if r is None:
            r = rows[k] = new_row(day, sid, mdl, side)
        if not r["project"] and cwd:
            r["project"] = _clean(_home_abbrev(cwd))
        return r

    def touch(r, ep):
        r["first_ts"] = ep if not r["first_ts"] else min(r["first_ts"], ep)
        r["last_ts"] = max(r["last_ts"], ep)

    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            rep.bad_lines += 1
            continue
        if not isinstance(rec, dict):
            rep.bad_lines += 1
            continue
        typ = rec.get("type")
        ep = _epoch(rec.get("timestamp"))
        if ep is None or typ not in ("assistant", "system"):
            continue
        day = local_day(ep)
        sid = _clean(rec.get("sessionId") or fsid)
        side = 1 if (fside or rec.get("isSidechain") is True) else 0
        cwd = rec.get("cwd") if isinstance(rec.get("cwd"), str) else ""

        if typ == "assistant":
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            m = msg.get("model")
            q = rec.get("quotaLimits")
            if m == "<synthetic>" or rec.get("isApiErrorMessage"):
                # A usage-limit refusal: not a request, but a budget event.
                if isinstance(q, dict) and isinstance(q.get("resetsAt"), int) \
                        and isinstance(q.get("rateLimitType"), str):
                    lk = (_clean(q["rateLimitType"]), str(q["resetsAt"]))
                    li = limits.setdefault(lk, {"type": lk[0], "resets_at": lk[1],
                                                "first_ts": ep, "last_ts": ep})
                    li["first_ts"] = min(int(li["first_ts"]), ep)
                    li["last_ts"] = max(int(li["last_ts"]), ep)
                continue
            u = msg.get("usage")
            if not isinstance(u, dict) or not isinstance(m, str) or not m:
                continue
            model = _clean(m)
            key = _h("msg", msg.get("id") or rec.get("uuid"), rec.get("requestId"))
            owner = seen.owner(day, key)
            if owner is not None and owner != fid:
                rep.copies += 1
                continue
            r = row(day, sid, model, side, cwd)
            touch(r, ep)
            tools = [b.get("name") for b in (msg.get("content") or [])
                     if isinstance(b, dict) and b.get("type") == "tool_use"]
            if tools:
                mix = _mix_parse(r["tool_mix"])
                for t in tools:
                    t = _clean(t or "?").replace(";", ",").replace("=", "-")
                    mix[t] = mix.get(t, 0) + 1
                r["tool_mix"] = _mix_str(mix)
                r["tools"] += len(tools)
            if owner == fid:
                rep.duplicate_lines += 1
                continue
            seen.claim(day, key, fid)
            rep.requests += 1
            cw = _num(u, "cache_creation_input_tokens")
            cc = u.get("cache_creation")
            w1h = _num(cc, "ephemeral_1h_input_tokens")
            w5m = _num(cc, "ephemeral_5m_input_tokens") if isinstance(cc, dict) else cw
            inp, rd = _num(u, "input_tokens"), _num(u, "cache_read_input_tokens")
            ctx = inp + rd + cw
            stu = u.get("server_tool_use")
            r["requests"] += 1
            r["in"] += inp
            r["out"] += _num(u, "output_tokens")
            r["cache_read"] += rd
            r["cache_w5m"] += w5m
            r["cache_w1h"] += w1h
            r["thinking"] += _num(u.get("output_tokens_details"), "thinking_tokens")
            r["ctx_peak"] = max(r["ctx_peak"], ctx)
            r["ctx_sum"] += ctx
            r["ctx_n"] += 1
            r["web"] += _num(stu, "web_search_requests") + _num(stu, "web_fetch_requests")
        else:
            sub = rec.get("subtype")
            if sub not in ("turn_duration", "compact_boundary"):
                continue
            # A resumed session copies these too, uuid and all.
            key = (_h("sys", rec["uuid"]) if rec.get("uuid")
                   else _h("sys", sid, sub, ep, rec.get("durationMs")))
            if seen.owner(day, key) is not None:
                if seen.owner(day, key) != fid:
                    rep.copies += 1
                continue
            seen.claim(day, key, fid)
            r = row(day, sid, model or "-", side, cwd)
            touch(r, ep)
            if sub == "turn_duration":
                r["turns"] += 1
                r["active_s"] += int(round(_num(rec, "durationMs") / 1000))
            else:
                r["compactions"] += 1
    return model


# ------------------------------------------------------------------ CLI
def _paths(a) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    prof = a.profile if a.profile is not None else profile_of(os.environ.get("CLAUDE_CONFIG_DIR"))
    cfg = pathlib.Path(a.config_dir) if a.config_dir else config_dir_of(prof)
    st = pathlib.Path(a.state_dir) if a.state_dir else stats_dir(prof)
    wd = pathlib.Path(a.wd_dir) if a.wd_dir else watchdog_dir(prof)
    return cfg, st, wd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="muxstats", description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", default=None, help="account name ('' = default)")
    ap.add_argument("--config-dir", help="Claude config dir (default: the account's)")
    ap.add_argument("--state-dir", help="stats dir (default: $XDG_STATE_HOME/muxtopus/stats[-P])")
    ap.add_argument("--wd-dir", help="watchdog state dir, for lanes and budget")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("collect", help="read new transcript bytes into the ledger")
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        cfg, st, wd = _paths(a)
        print(collect(cfg, st, wd_dir=wd).line())
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
