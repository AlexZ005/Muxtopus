#!/usr/bin/env python3
"""muxstats -- a ledger of what was used, counted once, that outlives the
transcripts it was read from.

    python3 muxstats.py collect [--profile P]    read what is new, update the ledger
    python3 muxstats.py stats [--week|--month|--all] [--by model] [--json|--csv|--md]
    muxtopus stats ...                            the same, from the launcher
    muxtopus stats --forget [--before DATE]       the off switch

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
      budget.tsv    one row per 5h window: peak %, week %, limited s, hits, resumes
      weeks.tsv     one row per weekly reset: the last week % before it
      lanes.tsv     one row per lane: parent, launched, done, forks, stranded
      meta          schema, collecting-since, last collect, backfill

MEASURED, and the reason for the dedupe index: one API
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
# three-day session. `hours` is tokens by LOCAL hour of day, "9=1234;10=56"
# (the rhythm row has no finer grain to draw from). `tool_mix` is
# "Name=count;..." sorted by name -- tool NAMES only, never their input. A `coarse` row is a day backfilled from
# Claude Code's own stats-cache.json: its single total is in `in`, everything
# else is 0, and it counts toward totals only.
LEDGER_COLS = (
    "day", "session", "project", "lane", "model", "side",
    "requests", "in", "out", "cache_read", "cache_w5m", "cache_w1h", "thinking",
    "ctx_peak", "ctx_sum", "ctx_n", "tools", "web", "turns", "active_s",
    "compactions", "first_ts", "last_ts", "hours", "tool_mix", "coarse",
)
TEXT_COLS = ("day", "session", "project", "lane", "model", "hours", "tool_mix")
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
    """The account's Claude config dir, by profile.sh's mux_config_of:
    ~/.claude or ~/.claude-<profile>. CLAUDE_CONFIG_DIR only ever picks the
    PROFILE (profile_of) -- used as a path, a work session's environment
    would feed the work transcripts into the default account's ledger."""
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
             side=side, hours="", tool_mix="")
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


def _mix_str(d: dict, numeric: bool = False) -> str:
    keys = sorted(d, key=int) if numeric else sorted(d)
    return ";".join("%s=%d" % (k, d[k]) for k in keys)


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
            stats_cache=None, schedules_dir=None, handovers_dir=None) -> CollectReport:
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
    # `stats --forget` leaves this behind: nothing older is ever counted
    # again, so a re-read transcript cannot bring a forgotten day back.
    cutoff = int(meta.get("forget_before") or 0)

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
                                rows, seen, limits, lanes, rep, cutoff)
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
            if cutoff and _day_start(day) < cutoff:
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
    # "Collecting since" is the first day with REAL rows: a coarse day is a
    # total, not a day this ledger watched, and the thin-data rule counts
    # watched days.
    since = min((r["day"] for r in ledger if not r["coarse"]), default="")
    meta["schema"] = str(SCHEMA)
    if since and (not meta.get("since") or since < meta["since"]):
        meta["since"] = since
    meta.setdefault("since", local_day(now))

    budget_collect(state, wd_dir, limits, cutoff)
    lanes_collect(state, wd_dir, schedules_dir, handovers_dir, cutoff)
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
            rep: CollectReport, cutoff: int = 0) -> str:
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
        if ep is None or typ not in ("assistant", "system") or ep < cutoff:
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
            hrs = _mix_parse(r["hours"])
            hr = str(_dt.datetime.fromtimestamp(ep).hour)
            hrs[hr] = hrs.get(hr, 0) + inp + rd + cw + _num(u, "output_tokens")
            r["hours"] = _mix_str(hrs, numeric=True)
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


# ------------------------------------------------------------- budget
# budget.tsv: one row per 5-hour window, keyed by its reset instant. The
# sources are the usage cache's log (claude-usage.sh: a reading an hour), the
# watchdog's log (resumes, wind-downs) and limits.tsv (the refusals the
# transcripts recorded). Every one of them can be rotated or cleaned away, so a
# row is MERGED field by field with max() into what was kept before: a count
# never shrinks because its source did, and re-reading the same source changes
# nothing.
BUDGET_COLS = ("reset_at", "day", "window_start", "session_peak_pct", "week_pct",
               "limited_s", "hits", "resumes", "winddowns")
WEEK_COLS = ("reset_at", "day", "week_pct", "sampled_at", "hits")
WINDOW_S = 5 * 3600
# Readings name a reset to the minute and the API to the second, and a probe
# can print 22:39 for a window the API says ends at 22:40.
TOLERANCE_S = 900

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _local_epoch(y, mo, d, h, mi) -> int | None:
    """A local wall-clock time to an instant, DST-aware (mktime decides)."""
    import time
    try:
        return int(time.mktime((y, mo, d, h, mi, 0, 0, 0, -1)))
    except (OverflowError, ValueError):
        return None


def _parse_hhmm(s: str) -> tuple[int, int] | None:
    import re
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*$", s or "", re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59 or (not m.group(2) and not ap):
        return None
    return h, mi


def _wall_after(ts: int, hm: tuple[int, int], slack: int = 600) -> int | None:
    """The first occurrence of a wall-clock time at or after `ts - slack`."""
    d = _dt.datetime.fromtimestamp(ts)
    for add in (0, 1, 2):
        dd = d.date() + _dt.timedelta(days=add)
        e = _local_epoch(dd.year, dd.month, dd.day, hm[0], hm[1])
        if e is not None and e >= ts - slack:
            return e
    return None


def _wall_before(ts: int, hm: tuple[int, int], slack: int = 600) -> int | None:
    """The last occurrence of a wall-clock time at or before `ts + slack`."""
    d = _dt.datetime.fromtimestamp(ts)
    for sub in (0, 1, 2):
        dd = d.date() - _dt.timedelta(days=sub)
        e = _local_epoch(dd.year, dd.month, dd.day, hm[0], hm[1])
        if e is not None and e <= ts + slack:
            return e
    return None


def _week_reset(ts: int, s: str) -> int | None:
    """"Sep 19, 17:00" read at `ts` -> an instant; the year is the reading's,
    or the next one when that puts the reset half a year in the past."""
    import re
    m = re.match(r"^\s*([A-Za-z]{3})[a-z]*\s+(\d{1,2}),?\s+(.+)$", s or "")
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    hm = _parse_hhmm(m.group(3))
    if not hm:
        return None
    y = _dt.datetime.fromtimestamp(ts).year
    e = _local_epoch(y, _MONTHS[m.group(1).lower()], int(m.group(2)), hm[0], hm[1])
    if e is not None and e < ts - 180 * 86400:
        e = _local_epoch(y + 1, _MONTHS[m.group(1).lower()], int(m.group(2)), hm[0], hm[1])
    return e


def _log_lines(path: pathlib.Path):
    """(epoch, rest) for every `YYYY-mm-dd HH:MM:SS<sep>rest` line."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        if len(line) < 20 or line[4] != "-" or line[13] != ":":
            continue
        try:
            t = _dt.datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        e = _local_epoch(t.year, t.month, t.day, t.hour, t.minute)
        if e is None:
            continue
        yield e + t.second, line[19:].lstrip("\t ")


def _near(keys, ep: int, tol: int = TOLERANCE_S):
    best = None
    for k in keys:
        if abs(k - ep) <= tol and (best is None or abs(k - ep) < abs(best - ep)):
            best = k
    return best


def budget_collect(state, wd_dir, limits: dict, cutoff: int = 0) -> None:
    state = pathlib.Path(state)
    old = {}
    for d in _read_tsv(state / "budget.tsv", BUDGET_COLS):
        try:
            old[int(d["reset_at"])] = {c: int(d[c] or 0) for c in BUDGET_COLS if c not in ("day",)}
        except ValueError:
            continue
    oldw = {}
    for d in _read_tsv(state / "weeks.tsv", WEEK_COLS):
        try:
            oldw[int(d["reset_at"])] = {c: int(d[c] or 0) for c in WEEK_COLS if c != "day"}
        except ValueError:
            continue

    win, weeks = {}, {}

    def window(reset_at: int) -> dict:
        k = _near(win, reset_at)
        if k is None:
            k = reset_at
            win[k] = {"reset_at": k, "window_start": k - WINDOW_S, "session_peak_pct": 0,
                      "week_pct": 0, "limited_s": 0, "hits": 0, "resumes": 0, "winddowns": 0}
        return win[k]

    def week(reset_at: int) -> dict:
        k = _near(weeks, reset_at, 3600)
        if k is None:
            k = reset_at
            weeks[k] = {"reset_at": k, "week_pct": 0, "sampled_at": 0, "hits": 0}
        return weeks[k]

    wd = pathlib.Path(wd_dir) if wd_dir else None
    if wd:
        for ts, rest in _log_lines(wd / "usage.log"):
            if rest.startswith("READ FAILED"):
                continue
            cur, spct, wpct, sres, wres = None, None, None, None, None
            for kv in rest.split("\t"):
                k, _, v = kv.partition("=")
                pct = v.rstrip("%")
                if k == "session":
                    cur, spct = "s", int(pct) if pct.isdigit() else None
                elif k == "week":
                    cur, wpct = "w", int(pct) if pct.isdigit() else None
                elif k == "resets" and cur == "s":
                    sres = v
                elif k == "resets" and cur == "w":
                    wres = v
            hm = _parse_hhmm(sres) if sres else None
            reset = _wall_after(ts, hm) if hm else None
            # A reading names the reset of the window it is IN; anything
            # further out than one window is a stale panel, not a window.
            if reset is not None and spct is not None and reset - ts <= WINDOW_S + 600:
                w = window(reset)
                w["session_peak_pct"] = max(w["session_peak_pct"], spct)
                if wpct is not None:
                    w["week_pct"] = max(w["week_pct"], wpct)
            wr = _week_reset(ts, wres) if wres else None
            if wr is not None and wpct is not None and ts <= wr:
                wk = week(wr)
                if ts >= wk["sampled_at"]:
                    wk["sampled_at"], wk["week_pct"] = ts, wpct

        import re
        for ts, rest in _log_lines(wd / "log"):
            m = re.match(r"^prompted \S+ in .* after reset (\S+)\s*$", rest)
            if m:
                hm = _parse_hhmm(m.group(1))
                reset = _wall_before(ts, hm) if hm else None
                if reset is not None:
                    window(reset)["resumes"] += 1
                continue
            if rest.startswith("wound down "):
                k = next((k for k in sorted(win) if k - WINDOW_S <= ts < k + 60), None)
                (win[k] if k is not None else window(ts + WINDOW_S))["winddowns"] += 1

    for (typ, resets_at), li in sorted(limits.items()):
        try:
            ra, first = int(resets_at), int(li["first_ts"])
        except (TypeError, ValueError):
            continue
        if first < cutoff:
            continue
        if typ == "five_hour":
            w = window(ra)
            w["hits"] = max(w["hits"], 1)
            w["limited_s"] = max(w["limited_s"], max(0, ra - first))
            w["session_peak_pct"] = max(w["session_peak_pct"], 100)
        elif typ == "seven_day":
            week(ra)["hits"] = 1

    win = {k: w for k, w in win.items() if w["window_start"] >= cutoff}
    weeks = {k: w for k, w in weeks.items() if k >= cutoff}
    # Merge into what was kept: max() per field, matched within the tolerance.
    for k, w in win.items():
        ok = _near(old, k)
        if ok is None:
            old[k] = dict(w)
        else:
            for c, v in w.items():
                if c != "reset_at":
                    old[ok][c] = max(old[ok].get(c, 0), v)
    for k, w in weeks.items():
        ok = _near(oldw, k, 3600)
        if ok is None:
            oldw[k] = dict(w)
        elif w["sampled_at"] >= oldw[ok]["sampled_at"]:
            oldw[ok].update(week_pct=w["week_pct"], sampled_at=w["sampled_at"],
                            hits=max(oldw[ok]["hits"], w["hits"]))
        else:
            oldw[ok]["hits"] = max(oldw[ok]["hits"], w["hits"])

    rows = []
    for k in sorted(old):
        r = dict(old[k])
        # A window nothing happened in is not a window worth a row.
        if not (r["session_peak_pct"] or r["hits"] or r["resumes"] or r["winddowns"]):
            continue
        r["day"] = local_day(r["window_start"])
        rows.append(r)
    wrows = []
    for k in sorted(oldw):
        r = dict(oldw[k])
        r["day"] = local_day(r["reset_at"])
        wrows.append(r)
    if rows or (state / "budget.tsv").exists():
        _write_if_changed(state / "budget.tsv", _tsv(rows, BUDGET_COLS))
    if wrows or (state / "weeks.tsv").exists():
        _write_if_changed(state / "weeks.tsv", _tsv(wrows, WEEK_COLS))


# -------------------------------------------------------------- lanes
# lanes.tsv: one row per lane slug. Sources: the watchdog's tree.tsv (which it
# prunes after 14 days, hence this file), schedule entries' `launched:`
# stamps, handovers/done/ (the mtime of a finished STATUS file is when the
# lane was marked done), QUESTIONS files (fork COUNTS only) and the log's
# `stranded:` lines. Merged into what was kept, like budget.tsv.
LANE_COLS = ("slug", "parent", "launched", "done", "questions_asked",
             "questions_answered", "stranded")
# The fork rules of muxtelegram.py (docs/handovers.md), mirrored:
# a file is answered iff a line matches ^\W*ANSWERED\b; a fork starts at a
# `## ` heading or a top-level `N.` item; a fork is answered when one of its
# lines starts `**Answer`.
_ANSWERED_RE = r"^\W*ANSWERED\b"
_FORK_RE = r"^\s*(\d+\.|##\s)"
_ANSWER_RE = r"^\s*\*\*Answer"


# claude-watchdog.sh MAX_SLUG, copied rather than imported: this module stands
# alone (it imports nothing of the dashboard's). tests/test_slug_limit.py
# asserts it agrees with the shell and with dashboard.naming.MAX_SLUG -- a
# stale copy here would count a 30-character lane under a name that no window
# and no handover file carries.
_MAX_SLUG = 32


def _sched_slug(raw: str) -> str:
    """claude-watchdog.sh sched_sanitise: [A-Za-z0-9._-], the rest '-', cut
    to _MAX_SLUG."""
    import re
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:_MAX_SLUG]


def _sched_header(path: pathlib.Path) -> dict:
    out = {}
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line == "---":
                    break
                k, sep, v = line.partition(": ")
                if sep and k and k not in out:
                    out[k] = v
    except OSError:
        pass
    return out


def fork_counts(text: str) -> tuple[int, int]:
    import re
    forks, answered, cur = 0, 0, False
    for line in text.splitlines():
        if re.match(_FORK_RE, line):
            forks += 1
            cur = False
        elif forks and not cur and re.match(_ANSWER_RE, line):
            answered += 1
            cur = True
    if re.search(_ANSWERED_RE, text, re.M):
        answered = forks
    return forks, answered


def lanes_collect(state, wd_dir, schedules_dir, handovers_dir, cutoff: int = 0) -> None:
    import re
    state = pathlib.Path(state)
    old = {d["slug"]: d for d in _read_tsv(state / "lanes.tsv", LANE_COLS) if d["slug"]}
    new: dict[str, dict] = {}

    def lane(slug):
        return new.setdefault(slug, {"slug": slug, "parent": "", "launched": "", "done": "",
                                     "questions_asked": "", "questions_answered": "",
                                     "stranded": ""})

    def earliest(r, ep):
        r["launched"] = str(ep) if not r["launched"] else str(min(int(r["launched"]), ep))

    wd = pathlib.Path(wd_dir) if wd_dir else None
    if wd:
        try:
            tree = (wd / "tree.tsv").read_text().splitlines()
        except OSError:
            tree = []
        for line in tree:
            f = line.split("\t")
            if len(f) < 6 or not f[0] or f[5] == "(adopted)":
                continue
            r = lane(_clean(f[0]))
            r["parent"] = r["parent"] or _clean(f[1])
            if f[4].isdigit():
                earliest(r, int(f[4]))
        stranded = {}
        for _, rest in _log_lines(wd / "log"):
            m = re.match(r"^stranded: (\S+)", rest)
            if m:
                # Lanes are named for their slug now; an older
                # release's windows still carry the markers.
                s = m.group(1).replace("➥", "")
                stranded[s] = stranded.get(s, 0) + 1
        for s, n in stranded.items():
            lane(_clean(s))["stranded"] = str(n)
    if schedules_dir:
        for p in sorted(pathlib.Path(schedules_dir).glob("*.md")):
            h = _sched_header(p)
            t = h.get("launched", "")
            try:
                lt = _dt.datetime.strptime(t.strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            slug = _sched_slug(h.get("slug") or h.get("title") or p.stem)
            r = lane(slug)
            r["parent"] = r["parent"] or _clean(h.get("parent", ""))
            ep = _local_epoch(lt.year, lt.month, lt.day, lt.hour, lt.minute)
            if ep is not None:
                earliest(r, ep)
    if handovers_dir:
        hd = pathlib.Path(handovers_dir)
        for p in sorted((hd / "done").glob("STATUS-*.md")):
            slug = re.sub(r"-\d{8}-\d{6}$", "", p.stem[len("STATUS-"):])
            try:
                mt = int(p.stat().st_mtime)
            except OSError:
                continue
            r = lane(slug)
            r["done"] = str(max(int(r["done"] or 0), mt))
        qs = {}
        for p in sorted(list(hd.glob("QUESTIONS-*.md")) + list((hd / "done").glob("QUESTIONS-*.md"))):
            slug = re.sub(r"-\d{8}-\d{6}$", "", p.stem[len("QUESTIONS-"):])
            try:
                a, b = fork_counts(p.read_text(errors="replace"))
            except OSError:
                continue
            qa = qs.setdefault(slug, [0, 0])
            qa[0] += a
            qa[1] += b
        for slug, (a, b) in qs.items():
            r = lane(slug)
            r["questions_asked"], r["questions_answered"] = str(a), str(b)

    for slug, r in new.items():
        o = old.get(slug)
        if o is None:
            old[slug] = r
            continue
        o["parent"] = o["parent"] or r["parent"]
        if r["launched"]:
            o["launched"] = r["launched"] if not o["launched"] else str(min(int(o["launched"]), int(r["launched"])))
        if r["done"]:
            o["done"] = str(max(int(o["done"] or 0), int(r["done"])))
        if r["questions_asked"]:
            o["questions_asked"], o["questions_answered"] = r["questions_asked"], r["questions_answered"]
        if r["stranded"]:
            o["stranded"] = str(max(int(o["stranded"] or 0), int(r["stranded"])))
    if cutoff:
        old = {k: r for k, r in old.items() if not _lane_forgotten(r, cutoff)}
    rows = [old[k] for k in sorted(old)]
    if rows or (state / "lanes.tsv").exists():
        _write_if_changed(state / "lanes.tsv", _tsv(rows, LANE_COLS))


def _lane_forgotten(r: dict, cutoff: int) -> bool:
    """A lane is forgotten when its last date is before the cutoff; one with
    no date at all (only forks or stranded counts) shows in no figure, and
    goes with any forget."""
    stamps = [int(r[c]) for c in ("launched", "done") if (r.get(c) or "").isdigit()]
    return not stamps or max(stamps) < cutoff


def _day_start(day: str) -> int:
    d = _d(day)
    return _local_epoch(d.year, d.month, d.day, 0, 0) or 0


# ---------------------------------------------------------------- prices
class PriceTable:
    """$ per million tokens per model, and each model's context window.

    A block matches a model id EXACTLY, or with a date suffix
    (claude-haiku-4-5 matches claude-haiku-4-5-20251001). Deliberately not a
    looser prefix: claude-fable-5 must not price a future claude-fable-5-2 --
    a model the file does not name shows `no price`, never a guess.
    """
    FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")

    def __init__(self, models: dict | None = None, as_of: str = "", errors=None):
        self.models = models or {}
        self.as_of = as_of
        self.errors = list(errors or [])

    def entry(self, model: str) -> dict | None:
        import re
        if model in self.models:
            return self.models[model]
        m = re.match(r"^(.*)-\d{8}$", model or "")
        return self.models.get(m.group(1)) if m else None

    def price(self, model: str) -> dict | None:
        e = self.entry(model)
        return e if e and all(isinstance(e.get(f), (int, float)) for f in self.FIELDS) else None

    def window(self, model: str) -> int | None:
        e = self.entry(model)
        w = e.get("window") if e else None
        return w if isinstance(w, int) and w > 0 else None


def cost(row: dict, table: PriceTable | None) -> float | None:
    """API-equivalent dollars for one ledger row; None when unpriced (or coarse,
    whose single total has no split to price)."""
    if table is None or row.get("coarse"):
        return None
    p = table.price(row["model"])
    if p is None:
        return None
    return (row["in"] * p["input"] + row["out"] * p["output"]
            + row["cache_read"] * p["cache_read"] + row["cache_w5m"] * p["cache_write_5m"]
            + row["cache_w1h"] * p["cache_write_1h"]) / 1e6


# ----------------------------------------------------------------- load
@dataclasses.dataclass
class Ledger:
    rows: list
    meta: dict
    budget: list
    weeks: list
    lanes: list


def load(state_dirs) -> Ledger:
    """One account's stats dir, or several merged (the `a` view: accounts'
    sessions are distinct, so rows simply concatenate)."""
    if isinstance(state_dirs, (str, os.PathLike)):
        state_dirs = [state_dirs]
    rows, budget, weeks, lanes, sinces, meta = [], [], [], [], [], {}
    for sd in state_dirs:
        sd = pathlib.Path(sd)
        rows += load_ledger(sd)
        for d in _read_tsv(sd / "budget.tsv", BUDGET_COLS):
            budget.append({c: (d[c] if c == "day" else int(d[c] or 0)) for c in BUDGET_COLS})
        for d in _read_tsv(sd / "weeks.tsv", WEEK_COLS):
            weeks.append({c: (d[c] if c == "day" else int(d[c] or 0)) for c in WEEK_COLS})
        lanes += _read_tsv(sd / "lanes.tsv", LANE_COLS)
        m = load_meta(sd)
        if m.get("since"):
            sinces.append(m["since"])
        meta.setdefault("last_collect", m.get("last_collect", ""))
    meta["since"] = min(sinces) if sinces else ""
    return Ledger(rows, meta, budget, weeks, lanes)


# ---------------------------------------------------------------- query
PERIODS = ("today", "week", "last7", "month", "last30", "all")
PERIOD_LABELS = {"today": "today", "week": "this week", "last7": "last 7 d",
                 "month": "this month", "last30": "last 30 d", "all": "all"}
GROUPS = ("project", "model", "lane", "day", "week", "month", "session", "side")
FILTER_KEYS = ("project", "model", "lane", "side", "session")
THIN_DAYS = 7


def _d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def period_range(name: str, today: _dt.date, first: _dt.date | None = None):
    """(start, end, prev_start, prev_end), all inclusive local dates. A week
    starts on Monday. The previous period is the SAME ELAPSED LENGTH, so a
    Wednesday compares Mon-Wed with last Mon-Wed, not with a whole week."""
    D = _dt.timedelta
    if name == "today":
        return today, today, today - D(1), today - D(1)
    if name == "week":
        s = today - D(today.weekday())
        return s, s + D(6), s - D(7), today - D(7)
    if name == "last7":
        return today - D(6), today, today - D(13), today - D(7)
    if name == "month":
        s = today.replace(day=1)
        nxt = (s + D(32)).replace(day=1)
        ps = (s - D(1)).replace(day=1)
        pe = min(ps + (today - s), s - D(1))
        return s, nxt - D(1), ps, pe
    if name == "last30":
        return today - D(29), today, today - D(59), today - D(30)
    if name == "all":
        return (first or today), today, None, None
    raise ValueError("unknown period: %s" % name)


def _tokens(r: dict) -> int:
    return r["in"] + r["out"] + r["cache_read"] + r["cache_w5m"] + r["cache_w1h"]


def _match(r: dict, filters: dict) -> bool:
    for k, vals in (filters or {}).items():
        if not vals:
            continue
        if k == "side":
            v = "sub" if r["side"] else "main"
        else:
            v = r.get(k, "")
        if v not in vals:
            return False
    return True


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _group_key(r: dict, g: str) -> str:
    if g == "side":
        return "sub" if r["side"] else "main"
    if g == "week":
        d = _d(r["day"])
        return (d - _dt.timedelta(d.weekday())).isoformat()
    if g == "month":
        return r["day"][:7]
    return str(r.get(g, ""))


def query(ledger: Ledger, period: str = "week", filters: dict | None = None,
          group_by: str = "project", now: int | None = None,
          table: PriceTable | None = None) -> dict:
    """Every figure the insights view shows for one period, from rows alone. A
    figure that needs a distribution is None, with the reason in `needs`,
    until THIN_DAYS days have been collected."""
    now = int(now if now is not None else _dt.datetime.now().timestamp())
    today = _dt.date.fromtimestamp(now)
    filters = {k: list(v) for k, v in (filters or {}).items() if v}
    if group_by not in GROUPS:
        raise ValueError("unknown group: %s" % group_by)
    since = ledger.meta.get("since") or ""
    all_days = [r["day"] for r in ledger.rows]
    first = _d(min(all_days)) if all_days else None
    start, end, pstart, pend = period_range(period, today, first)
    last = min(end, today)
    collected = (today - _d(since)).days + 1 if since else 0
    thin = collected < THIN_DAYS
    needs = {}

    def withhold(key, why="%d days" % THIN_DAYS):
        needs[key] = why
        return None

    rows_f = [r for r in ledger.rows if _match(r, filters)]
    inp = [r for r in rows_f if start.isoformat() <= r["day"] <= end.isoformat()]
    real = [r for r in inp if not r["coarse"]]
    coarse = [r for r in inp if r["coarse"]]

    S = lambda rs, c: sum(r[c] for r in rs)  # noqa: E731
    total_real = sum(_tokens(r) for r in real)
    coarse_tok = S(coarse, "in")
    total = total_real + coarse_tok
    out = S(real, "out")
    active = S(real, "active_s")
    writes = S(real, "cache_w5m") + S(real, "cache_w1h")
    fed = S(real, "in") + S(real, "cache_read") + writes

    rep = {
        "period": {"name": period, "label": PERIOD_LABELS[period],
                   "start": start.isoformat(), "end": end.isoformat(),
                   "prev_start": pstart.isoformat() if pstart else None,
                   "prev_end": pend.isoformat() if pend else None},
        "now": now, "since": since, "collected_days": collected, "thin": thin,
        "filters": filters, "group_by": group_by,
        "prices_as_of": table.as_of if table else None,
    }
    rep["tokens"] = {
        "total": total, "input": S(real, "in"), "output": out,
        "cache_read": S(real, "cache_read"), "cache_write": writes, "coarse": coarse_tok,
        "thinking_share": (S(real, "thinking") / out) if out else None,
        "per_active_hour": (total_real / (active / 3600)) if active else None,
    }

    priced_usd, unpriced, unpriced_tok, saved = 0.0, set(), 0, 0.0
    for r in real:
        c = cost(r, table)
        if c is None:
            # With no table at all, nothing is "unpriced": there are no prices.
            if _tokens(r) and table is not None:
                unpriced.add(r["model"])
                unpriced_tok += _tokens(r)
            continue
        priced_usd += c
        p = table.price(r["model"])
        saved += (r["cache_read"] * (p["input"] - p["cache_read"])
                  - r["cache_w5m"] * (p["cache_write_5m"] - p["input"])
                  - r["cache_w1h"] * (p["cache_write_1h"] - p["input"])) / 1e6
    have_price = table is not None and (total_real - unpriced_tok > 0 or not real)
    rep["cache"] = {
        "read_share": (S(real, "cache_read") / fed) if fed else None,
        "write_5m": S(real, "cache_w5m"), "write_1h": S(real, "cache_w1h"),
        # NET of the write premium: what caching saved against sending the
        # same input uncached.
        "saved_usd": round(saved, 6) if have_price else None,
    }
    elapsed = max(1, (last - max(start, _d(since) if since else start)).days + 1)
    usd = round(priced_usd, 6) if have_price else None
    per_day = round(priced_usd / elapsed, 6) if have_price else None
    month_days = ((today.replace(day=1) + _dt.timedelta(32)).replace(day=1) - today.replace(day=1)).days
    rep["cost"] = {
        "usd": usd, "per_day": per_day,
        "projected_month": (withhold("cost.projected_month") if thin
                            else (round(per_day * month_days, 6) if per_day is not None else None)),
        "unpriced_models": sorted(unpriced), "unpriced_tokens": unpriced_tok,
        "elapsed_days": elapsed,
    }

    # CONTEXT: the peak of a session is its main conversation's, where a
    # window filling up is the thing worth knowing.
    peaks = {}
    for r in real:
        if r["side"] or not r["ctx_n"]:
            continue
        p = peaks.get(r["session"])
        if p is None or r["ctx_peak"] > p[0]:
            peaks[r["session"]] = (r["ctx_peak"], r["model"])
    pcts = []
    for peak, model in peaks.values():
        w = table.window(model) if table else None
        if w:
            pcts.append(peak / w)
    ctx_n = S(real, "ctx_n")
    rep["context"] = {
        "avg_per_request": (S(real, "ctx_sum") / ctx_n) if ctx_n else None,
        "avg_session_peak": (sum(p for p, _ in peaks.values()) / len(peaks)) if peaks else None,
        "avg_session_peak_pct": (sum(pcts) / len(pcts)) if pcts else None,
        "sessions_past_80": sum(1 for x in pcts if x >= 0.8) if pcts else None,
        "sessions_measured": len(pcts),
        "compactions": S(real, "compactions"),
    }

    sess = {}
    for r in real:
        sess.setdefault(r["session"], 0)
        sess[r["session"]] += r["active_s"]
    act = [v for v in sess.values() if v > 0]
    mix = {}
    for r in real:
        for k, v in _mix_parse(r["tool_mix"]).items():
            mix[k] = mix.get(k, 0) + v
    sub_tok = sum(_tokens(r) for r in real if r["side"])
    rep["sessions"] = {
        "count": len(sess),
        "median_active_s": withhold("sessions.median_active_s") if thin else _median(act),
        "longest_active_s": max(act) if act else None,
        "turns_per_session": (S(real, "turns") / len(sess)) if sess else None,
        "subagent_share": (sub_tok / total_real) if total_real else None,
        "tool_calls": S(real, "tools"),
        "top_tools": sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
        "web": S(real, "web"),
    }

    bud = [b for b in ledger.budget if start.isoformat() <= b["day"] <= end.isoformat()]
    peaked = [b["session_peak_pct"] for b in bud if b["session_peak_pct"] > 0]
    wk = [w for w in ledger.weeks if start.isoformat() <= w["day"] <= end.isoformat()
          and w["reset_at"] <= now and w["sampled_at"]]
    rep["budget"] = {
        "windows": len(peaked), "hits": sum(b["hits"] for b in bud),
        "limited_s": sum(b["limited_s"] for b in bud),
        "resumes": sum(b["resumes"] for b in bud), "winddowns": sum(b["winddowns"] for b in bud),
        "avg_window_peak_pct": (sum(peaked) / len(peaked)) if peaked else None,
        "week_pct_at_reset": [[w["day"], w["week_pct"]] for w in sorted(wk, key=lambda w: w["reset_at"])],
    }

    rep["lanes"] = _lane_figures(ledger.lanes, start, end, filters, thin, withhold)
    rep["rhythm"] = _rhythm(rows_f, inp, start, last, pstart, pend, since, thin, withhold, total)

    groups = {}
    for r in inp:
        groups.setdefault(_group_key(r, group_by), []).append(r)
    bd = []
    for key, rs in groups.items():
        rr = [r for r in rs if not r["coarse"]]
        tok = sum(_tokens(r) for r in rr) + S([r for r in rs if r["coarse"]], "in")
        n = S(rr, "ctx_n")
        fd = S(rr, "in") + S(rr, "cache_read") + S(rr, "cache_w5m") + S(rr, "cache_w1h")
        costs = [cost(r, table) for r in rr if _tokens(r)]
        bd.append({"key": key, "tokens": tok, "share": (tok / total) if total else None,
                   "sessions": len({r["session"] for r in rr}),
                   "avg_ctx": (S(rr, "ctx_sum") / n) if n else None,
                   "cache_pct": (S(rr, "cache_read") / fd) if fd else None,
                   "usd": round(sum(c for c in costs if c is not None), 6)
                   if table is not None and any(c is not None for c in costs) else None,
                   "unpriced": any(c is None for c in costs)})
    if group_by in ("day", "week", "month"):
        bd.sort(key=lambda b: b["key"])
    else:
        bd.sort(key=lambda b: (-b["tokens"], b["key"]))
    rep["breakdown"] = bd
    rep["needs"] = needs
    return rep


def _lane_figures(lanes, start, end, filters, thin, withhold) -> dict:
    def day(ep):
        return local_day(int(ep)) if ep else ""
    want = filters.get("lane")
    ls = [l for l in lanes if not want or l["slug"] in want]
    s, e = start.isoformat(), end.isoformat()
    launched = [l for l in ls if l["launched"] and s <= day(l["launched"]) <= e]
    done = [l for l in ls if l["done"] and s <= day(l["done"]) <= e]
    spans = [int(l["done"]) - int(l["launched"]) for l in done
             if l["launched"] and int(l["done"]) >= int(l["launched"])]
    parent = {l["slug"]: l["parent"] for l in lanes}

    def depth(slug):
        n, seen = 0, set()
        while slug in parent and slug not in seen:
            seen.add(slug)
            n += 1
            slug = parent[slug]
        return n
    num = lambda l, c: int(l[c] or 0)  # noqa: E731
    return {
        "launched": len(launched), "done": len(done),
        "median_launch_to_done_s": withhold("lanes.median_launch_to_done_s") if thin else _median(spans),
        "deepest": max((depth(l["slug"]) for l in launched), default=0),
        "forks_asked": sum(num(l, "questions_asked") for l in launched),
        "forks_answered": sum(num(l, "questions_answered") for l in launched),
        "stranded": sum(num(l, "stranded") for l in launched),
    }


def _rhythm(rows_f, inp, start, last, pstart, pend, since, thin, withhold, total) -> dict:
    by_wd, by_hr, by_day = [0] * 7, [0] * 24, {}
    for r in inp:
        t = r["in"] if r["coarse"] else _tokens(r)
        by_day[r["day"]] = by_day.get(r["day"], 0) + t
        by_wd[_d(r["day"]).weekday()] += t
        for h, v in _mix_parse(r["hours"]).items():
            if h.isdigit() and 0 <= int(h) < 24:
                by_hr[int(h)] += v
    active_days = {r["day"] for r in rows_f
                   if (r["coarse"] and r["in"]) or (not r["coarse"] and (r["requests"] or r["turns"]))}
    D = _dt.timedelta
    cur, d = 0, last
    if d.isoformat() not in active_days:
        d -= D(1)                     # today is not over: a streak may end yesterday
    while d.isoformat() in active_days:
        cur += 1
        d -= D(1)
    longest, run, d = 0, 0, start
    while d <= last:
        run = run + 1 if d.isoformat() in active_days else 0
        longest = max(longest, run)
        d += D(1)
    vs = None
    prev_total = None
    if pstart is None:
        vs = None
    elif thin:
        vs = withhold("rhythm.vs_previous_pct")
    elif not since or pstart.isoformat() < since:
        vs = withhold("rhythm.vs_previous_pct", "a previous period")
    else:
        prev_total = sum((r["in"] if r["coarse"] else _tokens(r)) for r in rows_f
                         if pstart.isoformat() <= r["day"] <= pend.isoformat())
        cur_total = sum(v for k, v in by_day.items() if k <= last.isoformat())
        vs = ((cur_total - prev_total) / prev_total * 100) if prev_total else \
            withhold("rhythm.vs_previous_pct", "a previous period")
    return {
        "by_weekday": by_wd, "by_hour": by_hr,
        "busiest_day": max(sorted(by_day), key=lambda k: by_day[k]) if by_day and total else None,
        "busiest_hour": by_hr.index(max(by_hr)) if any(by_hr) else None,
        "streak": cur, "longest_streak": longest,
        "vs_previous_pct": vs, "previous_total": prev_total,
    }


# ----------------------------------------------------------- price file
PRICE_KEYS = PriceTable.FIELDS + ("window",)


def _window(v: str) -> int | None:
    v = v.strip().upper().replace(",", "").replace("_", "")
    mult = 1
    if v.endswith("M"):
        v, mult = v[:-1], 1_000_000
    elif v.endswith("K"):
        v, mult = v[:-1], 1_000
    try:
        n = float(v) * mult
    except ValueError:
        return None
    return int(n) if n > 0 else None


def prices(path) -> PriceTable | None:
    """The price and model table (seeds/prices.md). None when there is no
    file -- the report then shows tokens only. A malformed line is skipped
    and named in `errors`; the rest of the file still counts."""
    try:
        text = pathlib.Path(path).read_text(errors="replace")
    except OSError:
        return None
    models, errors, as_of = {}, [], ""
    cur, cur_line = None, 0

    def close():
        if cur is None:
            return
        name = cur.pop("model", "")
        if not name:
            errors.append("line %d: a block with no model:" % cur_line)
            return
        missing = [f for f in PriceTable.FIELDS if f not in cur]
        if missing:
            errors.append("line %d: %s has no %s -- shown as no price"
                          % (cur_line, name, ", ".join(missing)))
        models[name] = cur

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not line:
            close()
            cur = None
            continue
        k, sep, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if not sep:
            errors.append("line %d: not `key: value`" % n)
            continue
        if k == "as of":
            as_of = as_of or v
            continue
        if k == "source":
            continue
        if cur is None:
            cur, cur_line = {}, n
        if k == "model":
            if "model" in cur:
                errors.append("line %d: a second model: in one block" % n)
                continue
            cur["model"] = v
        elif k == "window":
            w = _window(v)
            if w is None:
                errors.append("line %d: window %r is not a token count" % (n, v))
            else:
                cur["window"] = w
        elif k in PriceTable.FIELDS:
            try:
                x = float(v.lstrip("$"))
                if x < 0:
                    raise ValueError
                cur[k] = x
            except ValueError:
                errors.append("line %d: %s %r is not a price" % (n, k, v))
        else:
            errors.append("line %d: unknown key %r" % (n, k))
    close()
    errors.sort(key=lambda e: int(e.split()[1].rstrip(":")))
    return PriceTable(models, as_of, errors)


def prices_path() -> pathlib.Path:
    """Beside the shared config: ~/.config/muxtopus/prices.md (muxconfig's
    config_path rule, repeated here to keep this module standalone)."""
    cfg = os.environ.get("MUXTOPUS_CONFIG") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or str(pathlib.Path.home() / ".config"),
        "muxtopus", "config")
    return pathlib.Path(cfg).parent / "prices.md"


# --------------------------------------------------------------- forget
def forget(state_dir, before: str | None = None, now: int | None = None) -> dict:
    """`stats --forget [--before DATE]`: drop what the ledger holds from
    before DATE (a local date), or everything up to now, and record the
    cutoff so no later collect counts it again. Transcripts are not touched."""
    state = pathlib.Path(state_dir)
    now = int(now if now is not None else _dt.datetime.now().timestamp())
    cutoff = _day_start(before) if before else now
    meta = load_meta(state)
    old_cut = int(meta.get("forget_before") or 0)
    out = {"cutoff": cutoff, "rows": 0, "windows": 0, "weeks": 0, "lanes": 0, "limits": 0, "months": 0}

    rows = load_ledger(state)
    keep = [r for r in rows if before and r["day"] >= before]
    out["rows"] = len(rows) - len(keep)
    b = _read_tsv(state / "budget.tsv", BUDGET_COLS)
    bk = [r for r in b if int(r["window_start"] or 0) >= cutoff]
    w = _read_tsv(state / "weeks.tsv", WEEK_COLS)
    wk = [r for r in w if int(r["reset_at"] or 0) >= cutoff]
    ln = _read_tsv(state / "lanes.tsv", LANE_COLS)
    lk = [r for r in ln if not _lane_forgotten(r, cutoff)]
    li = _read_tsv(state / "limits.tsv", LIMIT_COLS)
    lik = [r for r in li if int(r["first_ts"] or 0) >= cutoff]
    out.update(windows=len(b) - len(bk), weeks=len(w) - len(wk), lanes=len(ln) - len(lk),
               limits=len(li) - len(lik))
    month = local_day(cutoff)[:7]
    for f in sorted((state / "seen").glob("*.tsv")) if (state / "seen").is_dir() else []:
        if f.stem < month:
            f.unlink()
            out["months"] += 1

    _write_atomic(state / "ledger.tsv", _tsv(keep, LEDGER_COLS))
    for name, rs, cols in (("budget.tsv", bk, BUDGET_COLS), ("weeks.tsv", wk, WEEK_COLS),
                           ("lanes.tsv", lk, LANE_COLS), ("limits.tsv", lik, LIMIT_COLS)):
        if (state / name).exists():
            _write_atomic(state / name, _tsv(rs, cols))
    meta["forget_before"] = str(max(old_cut, cutoff))
    real = [r["day"] for r in keep if not r["coarse"]]
    meta["since"] = min(real) if real else local_day(cutoff)
    _write_atomic(state / "meta", "".join("%s\t%s\n" % (k, meta[k]) for k in sorted(meta)))
    return out


# ------------------------------------------------------------ rendering
# Plain text, no dependency: the dashboard draws the same Report with Rich.
SPARK = "▁▂▃▄▅▆▇█"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def human_tokens(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            return "%.1f%s" % (n / div, unit)
    return "%d" % n


def human_duration(s) -> str:
    if s is None:
        return "—"
    s = int(round(s))
    if s < 60:
        return "%ds" % s
    m = s // 60
    if m < 60:
        return "%dm" % m
    h, m = divmod(m, 60)
    if h < 24:
        return "%dh%02dm" % (h, m)
    d, h = divmod(h, 24)
    return "%dd%02dh" % (d, h)


def _pct(x) -> str:
    return "—" if x is None else "%d%%" % int(x * 100 + 0.5)


def _usd(x) -> str:
    if x is None:
        return "—"
    if 0 < x < 0.01:
        return "<$0.01"
    return "${:,.2f}".format(x)


def sparkline(vals) -> str:
    top = max(vals) if vals else 0
    if not top:
        return SPARK[0] * len(vals)
    return "".join(SPARK[min(len(SPARK) - 1, int(v / top * (len(SPARK) - 1) + 0.5))] if v else " "
                   for v in vals)


def _needs(rep, key, value_text):
    why = rep["needs"].get(key)
    return ("— needs %s" % why) if why else value_text


def title(rep: dict) -> str:
    p, f = rep["period"], rep["filters"]
    parts = ["insights", "%s (%s – %s)" % (p["label"], p["start"], p["end"])]
    parts.append(("project " + ", ".join(f["project"])) if f.get("project") else "all projects")
    parts.append(("model " + ", ".join(f["model"])) if f.get("model") else "all models")
    if f.get("lane"):
        parts.append("lane " + ", ".join(f["lane"]))
    if f.get("side"):
        parts.append("side " + ", ".join(f["side"]))
    if f.get("session"):
        parts.append("session " + ", ".join(x[:8] for x in f["session"]))
    since = rep["since"] or "—"
    return " · ".join(parts) + " — collecting since " + since


def figure_lines(rep: dict) -> list[tuple[str, str]]:
    """(ROW, figures) for the seven rows, as the text, markdown and dashboard
    faces all say them."""
    t, c, k, x, s, b, ln, r = (rep[n] for n in ("tokens", "cache", "cost", "context",
                                                "sessions", "budget", "lanes", "rhythm"))
    as_of = rep["prices_as_of"]
    tag = " API-equiv" + ((" (prices as of %s)" % as_of) if as_of else "")
    tok = ["%s total" % human_tokens(t["total"]),
           "in %s · out %s · cache read %s · cache write %s" % tuple(
               human_tokens(t[n]) for n in ("input", "output", "cache_read", "cache_write")),
           "thinking %s of output" % _pct(t["thinking_share"]),
           "%s / active hour" % human_tokens(t["per_active_hour"])]
    if t["coarse"]:
        tok.insert(1, "%s from coarse days" % human_tokens(t["coarse"]))
    cache = ["%s of input from cache" % _pct(c["read_share"]),
             "writes 5m %s / 1h %s" % (human_tokens(c["write_5m"]), human_tokens(c["write_1h"]))]
    if rep["prices_as_of"] is not None or c["saved_usd"] is not None:
        cache.append("saved %s%s" % (_usd(c["saved_usd"]), " API-equiv"))
    if k["usd"] is None:
        cost = ["— no price" + ("s: no price file, tokens only" if rep["prices_as_of"] is None else "")]
    else:
        cost = ["%s%s" % (_usd(k["usd"]), tag), "%s / day" % _usd(k["per_day"]),
                "month at this pace " + _needs(rep, "cost.projected_month", _usd(k["projected_month"]))]
    if k["unpriced_models"]:
        cost.append("no price: %s (%s tokens)" % (", ".join(k["unpriced_models"]),
                                                  human_tokens(k["unpriced_tokens"])))
    ctx = ["avg %s / request" % human_tokens(x["avg_per_request"]),
           "avg session peak %s%s" % (human_tokens(x["avg_session_peak"]),
                                      (" (%s of window)" % _pct(x["avg_session_peak_pct"]))
                                      if x["avg_session_peak_pct"] is not None else ""),
           "%s past 80%%" % ("—" if x["sessions_past_80"] is None else x["sessions_past_80"]),
           "%d compaction%s" % (x["compactions"], "" if x["compactions"] == 1 else "s")]
    tools = ", ".join("%s %d" % (n, v) for n, v in s["top_tools"])
    ses = ["%d" % s["count"],
           "median active " + _needs(rep, "sessions.median_active_s", human_duration(s["median_active_s"])),
           "longest " + human_duration(s["longest_active_s"]),
           "%s turns each" % ("—" if s["turns_per_session"] is None else "%.1f" % s["turns_per_session"]),
           "subagents %s" % _pct(s["subagent_share"]),
           "%d tool calls%s" % (s["tool_calls"], (" (%s)" % tools) if tools else ""),
           "%d web" % s["web"]]
    wk = ", ".join("%s %d%%" % (d[5:], v) for d, v in b["week_pct_at_reset"])
    bud = ["%d window%s, avg peak %s" % (b["windows"], "" if b["windows"] == 1 else "s",
                                         "—" if b["avg_window_peak_pct"] is None
                                         else "%d%%" % round(b["avg_window_peak_pct"])),
           "%d limit hit%s, %s limited" % (b["hits"], "" if b["hits"] == 1 else "s",
                                           human_duration(b["limited_s"])),
           "%d resume%s" % (b["resumes"], "" if b["resumes"] == 1 else "s"),
           "%d wind-down%s" % (b["winddowns"], "" if b["winddowns"] == 1 else "s")]
    if wk:
        bud.append("week at reset: " + wk)
    lan = ["%d launched" % ln["launched"],
           "%d done, median %s" % (ln["done"], _needs(rep, "lanes.median_launch_to_done_s",
                                                      human_duration(ln["median_launch_to_done_s"]))),
           "deepest %d" % ln["deepest"],
           "forks %d/%d answered" % (ln["forks_answered"], ln["forks_asked"]),
           "%d stranded" % ln["stranded"]]
    vs = r["vs_previous_pct"]
    vs_txt = ("—" if vs is None else ("%s %d%%" % ("▲" if vs >= 0 else "▼", round(abs(vs)))))
    rhy = ["weekday %s" % sparkline(r["by_weekday"]),
           "hour %s" % sparkline(r["by_hour"]),
           "busiest %s%s" % (r["busiest_day"] or "—",
                             (", %02d:00" % r["busiest_hour"]) if r["busiest_hour"] is not None else ""),
           "streak %d d (longest %d)" % (r["streak"], r["longest_streak"])]
    if rep["period"]["prev_start"]:
        rhy.append("vs previous " + _needs(rep, "rhythm.vs_previous_pct", vs_txt))
    return [("TOKENS", " · ".join(tok)), ("CACHE", " · ".join(cache)), ("COST", " · ".join(cost)),
            ("CONTEXT", " · ".join(ctx)), ("SESSIONS", " · ".join(ses)), ("BUDGET", " · ".join(bud)),
            ("LANES", " · ".join(lan)), ("RHYTHM", " · ".join(rhy))]


BREAKDOWN_COLS = ("tokens", "share", "sessions", "avg ctx", "cache", "$")


def _breakdown_cells(rep: dict) -> list[list[str]]:
    out = []
    for b in rep["breakdown"]:
        key = b["key"] or "—"
        if rep["group_by"] == "model" and key == "-":
            key = "(no model)"    # turns a session took before any request
        if rep["group_by"] == "side":
            key = {"main": "main", "sub": "subagents"}.get(key, key)
        usd = _usd(b["usd"]).lstrip("$") if b["usd"] is not None else "—"
        out.append([key, human_tokens(b["tokens"]), _pct(b["share"]), str(b["sessions"]),
                    human_tokens(b["avg_ctx"]), _pct(b["cache_pct"]),
                    usd + ("*" if b["unpriced"] and b["usd"] is not None else "")])
    return out


def render_text(rep: dict) -> str:
    lines = [title(rep), ""]
    for row, text in figure_lines(rep):
        lines.append("%-9s %s" % (row, text))
    cells = _breakdown_cells(rep)
    lines.append("")
    head = ["BY " + rep["group_by"].upper()] + list(BREAKDOWN_COLS)
    if cells:
        wid = [max(len(r[i]) for r in cells + [head]) for i in range(len(head))]
        fmt = lambda r: "  ".join(  # noqa: E731
            (v.ljust(wid[i]) if i == 0 else v.rjust(wid[i])) for i, v in enumerate(r)).rstrip()
        lines.append(fmt(head))
        lines += [fmt(r) for r in cells]
        if any(b["unpriced"] and b["usd"] is not None for b in rep["breakdown"]):
            lines.append("* part of that group's tokens has no price")
    else:
        lines.append(head[0] + ": nothing in this period")
    for e in rep.get("prices_errors") or []:
        lines.append("prices.md: " + e)
    return "\n".join(lines) + "\n"


def to_json(rep: dict) -> str:
    return json.dumps(rep, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def to_csv(rep: dict) -> str:
    """The breakdown table, one row per group -- the part a spreadsheet wants.
    Every figure is in --json."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([rep["group_by"], "tokens", "share", "sessions", "avg_ctx", "cache_pct", "usd", "unpriced"])
    for b in rep["breakdown"]:
        w.writerow([b["key"], b["tokens"],
                    "" if b["share"] is None else "%.4f" % b["share"],
                    b["sessions"],
                    "" if b["avg_ctx"] is None else "%.1f" % b["avg_ctx"],
                    "" if b["cache_pct"] is None else "%.4f" % b["cache_pct"],
                    "" if b["usd"] is None else "%.6f" % b["usd"],
                    int(b["unpriced"])])
    return buf.getvalue()


def to_md(rep: dict) -> str:
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    p = rep["period"]
    lines = ["# Insights — %s (%s – %s)" % (p["label"], p["start"], p["end"]), "",
             esc(title(rep)), "", "| row | figures |", "|---|---|"]
    lines += ["| %s | %s |" % (row, esc(text)) for row, text in figure_lines(rep)]
    lines += ["", "| %s | %s |" % (rep["group_by"], " | ".join(BREAKDOWN_COLS)),
              "|---|" + "---:|" * len(BREAKDOWN_COLS)]
    lines += ["| %s |" % " | ".join(esc(c) for c in r) for r in _breakdown_cells(rep)]
    lines += ["", "Counts only: no prompt, reply or tool input is recorded. "
              "$ figures are API-equivalent, not money spent."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ CLI
def _paths(a) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    prof = _profile(a)
    cfg = pathlib.Path(a.config_dir) if a.config_dir else config_dir_of(prof)
    st = pathlib.Path(a.state_dir) if a.state_dir else stats_dir(prof)
    wd = pathlib.Path(a.wd_dir) if a.wd_dir else watchdog_dir(prof)
    return cfg, st, wd


def _profile(a) -> str:
    return a.profile if a.profile is not None else profile_of(os.environ.get("CLAUDE_CONFIG_DIR"))


def _mux_dirs(profile: str):
    """schedules/ and handovers/ of the account, by muxconfig's rules; none
    when it cannot be imported (lanes then come from the tree alone)."""
    try:
        import muxconfig
        return muxconfig.mux_dir("schedules", profile), muxconfig.mux_dir("handovers", profile)
    except Exception:  # noqa: BLE001 -- a lane source is optional, a report is not
        return None, None


def _collect_cli(a, quiet=False) -> None:
    cfg, st, wd = _paths(a)
    sched, hand = (None, None) if a.config_dir or a.state_dir else _mux_dirs(_profile(a))
    rep = collect(cfg, st, a.now, wd_dir=wd, schedules_dir=sched, handovers_dir=hand)
    if not quiet:
        print(rep.line())


STATS_HELP = """\
muxtopus stats -- what was used, from the ledger (counts only)

  --today | --week | --last7 | --month | --last30 | --all     period (default --week)
  --project P  --model M  --lane L  --side main|sub           filter; repeat to OR
  --by project|model|lane|day|week|month|session|side          the breakdown (default project)
  --json | --csv | --md                                        output (default text)
  --prices FILE      price table (default ~/.config/muxtopus/prices.md)
  --no-collect       report the ledger as it is, without reading new transcripts
  --all-accounts     merge every account's ledger
  --forget [--before YYYY-MM-DD]   drop what is recorded (before that date, else
                     everything) and never count it again; transcripts are untouched
"""


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=argparse.SUPPRESS, help="account name ('' = default)")
    common.add_argument("--config-dir", default=argparse.SUPPRESS, help="Claude config dir")
    common.add_argument("--state-dir", default=argparse.SUPPRESS, help="stats dir")
    common.add_argument("--wd-dir", default=argparse.SUPPRESS, help="watchdog state dir")
    common.add_argument("--now", type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog="muxstats", parents=[common],
                                 description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("collect", parents=[common], help="read new transcript bytes into the ledger")
    sp = sub.add_parser("stats", parents=[common], help="the report", add_help=False)
    sp.add_argument("-h", "--help", action="store_true")
    per = sp.add_mutually_exclusive_group()
    for name in PERIODS:
        per.add_argument("--" + name, dest="period", action="store_const", const=name)
    for k in ("project", "model", "lane", "side", "session"):
        sp.add_argument("--" + k, action="append", default=[])
    sp.add_argument("--by", default="project", choices=GROUPS)
    fmt = sp.add_mutually_exclusive_group()
    for f in ("json", "csv", "md"):
        fmt.add_argument("--" + f, dest="fmt", action="store_const", const=f)
    sp.add_argument("--prices")
    sp.add_argument("--no-collect", action="store_true")
    sp.add_argument("--all-accounts", action="store_true")
    sp.add_argument("--forget", action="store_true")
    sp.add_argument("--before")
    a = ap.parse_args(argv)
    for k in ("profile", "config_dir", "state_dir", "wd_dir", "now"):
        if not hasattr(a, k):
            setattr(a, k, None)

    if a.cmd == "collect":
        _collect_cli(a)
        return 0
    if a.cmd != "stats":
        ap.print_help()
        return 2
    if a.help:
        sys.stdout.write(STATS_HELP)
        return 0
    if a.before and not a.forget:
        print("muxstats: --before goes with --forget", file=sys.stderr)
        return 2
    if a.side and any(s not in ("main", "sub") for s in a.side):
        print("muxstats: --side is main or sub", file=sys.stderr)
        return 2

    _, st, _ = _paths(a)
    if a.forget:
        if a.all_accounts:
            print("muxstats: --forget works on one account at a time", file=sys.stderr)
            return 2
        if a.before:
            try:
                _dt.date.fromisoformat(a.before)
            except ValueError:
                print("muxstats: --before wants YYYY-MM-DD, got %r" % a.before, file=sys.stderr)
                return 2
        out = forget(st, a.before, a.now)
        print("forgot %d ledger row(s), %d budget window(s), %d weekly reset(s), %d lane(s), "
              "%d limit hit(s), %d index month(s) %s; nothing older will be counted again (%s)"
              % (out["rows"], out["windows"], out["weeks"], out["lanes"], out["limits"],
                 out["months"], ("before " + a.before) if a.before else "up to now", st))
        return 0

    if not a.no_collect:
        try:
            _collect_cli(a, quiet=True)
        except Exception as e:  # noqa: BLE001 -- a stale report beats none
            print("muxstats: collect failed (%s: %s); reporting the ledger as it is"
                  % (type(e).__name__, e), file=sys.stderr)
    dirs = sorted(p for p in st.parent.glob("stats*") if p.is_dir()) if a.all_accounts else [st]
    led = load(dirs)

    filters = {"model": a.model, "lane": a.lane, "side": a.side, "session": a.session}
    if a.project:
        known = {r["project"] for r in led.rows}
        want = []
        for pr in a.project:
            hit = [k for k in known if k == pr] or \
                  [k for k in known if "/" not in pr and k.rstrip("/").rsplit("/", 1)[-1] == pr]
            want += hit or [pr]
        filters["project"] = sorted(set(want))
    ppath = pathlib.Path(a.prices) if a.prices else prices_path()
    table = prices(ppath)
    rep = query(led, a.period or "week", filters, a.by, a.now, table)
    rep["prices_errors"] = table.errors if table else []
    if a.all_accounts:
        rep["accounts"] = [d.name for d in dirs]
    if a.fmt == "json":
        sys.stdout.write(to_json(rep))
    elif a.fmt == "csv":
        sys.stdout.write(to_csv(rep))
    elif a.fmt == "md":
        sys.stdout.write(to_md(rep))
    else:
        sys.stdout.write(render_text(rep))
        if table is None:
            sys.stdout.write("no price file at %s -- tokens only (the seed is seeds/prices.md)\n" % ppath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
