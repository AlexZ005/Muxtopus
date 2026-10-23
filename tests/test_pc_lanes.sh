#!/usr/bin/env bash
# Lanes on another host (docs/pc-host.md, "Lanes on the pc host"): which host
# an entry runs on, the hand-over, the far status brought back, the tree's
# far panes, a report about a far lane typed to a parent here, the HOST
# columns, a host at its lane cap or asleep, a far launch that failed, and
# the far ledger in tokens-by-lane.jsonl.
#
#   bash tests/test_pc_lanes.sh
#
# THE FAR HOST IS A SECOND SANDBOX HOME. A fake `ssh` first on PATH runs the
# remote command here, with HOME=$SB/pc, its own muxtopus config and tmux
# server, and every "$SB/home" in the command rewritten to "$SB/pc": the
# design keeps paths equal on both machines, and the rewrite is what lets one
# machine play both while each side's files stay its own. A host named
# "dead" refuses, as an asleep PC does.
#
# SANDBOX: tests/notify_sandbox.sh for this side; the far side's tmux is -L
# mxpclanes-<pid>. Nothing here reaches a real host, the real tmux or the
# real state.
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
ST="$XDG_STATE_HOME/claude-watchdog"; SC="$HOME/.code/schedules"; HO="$HOME/.code/handovers"
PC="$SB/pc"; PST="$PC/.local/state/claude-watchdog"; PSC="$PC/.code/schedules"; PHO="$PC/.code/handovers"
PSOCK="mxpclanes-$$"
mkdir -p "$ST" "$PST" "$PSC/templates" "$PHO/done" "$PC/.config/muxtopus" "$PC/.local/state/muxtopus/stats" "$HOME/.claude/projects/p"
printf 'MUXTOPUS_HOME="%s"\nMUXTOPUS_TMUX_SOCKET=%s\nWATCHDOG_REPORT=off\n' "$PC/.code" "$PSOCK" > "$PC/.config/muxtopus/config"
: > "$PST/enabled"
REAL_TMUX="$(command -v -p tmux 2>/dev/null || PATH=/usr/bin:/bin command -v tmux)"
"$REAL_TMUX" -L "$PSOCK" -f /dev/null new-session -d -s claude -n status "sleep 900"
FARPANE="$("$REAL_TMUX" -L "$PSOCK" new-window -d -P -F '#{pane_id}' -t claude: -n pcl-1 "sleep 900")"
FARWID="$("$REAL_TMUX" -L "$PSOCK" display-message -p -t "$FARPANE" '#{window_id}')"
trap '"$REAL_TMUX" -L "$PSOCK" kill-server 2>/dev/null; sb_cleanup' EXIT

cat > "$HOME/.config/muxtopus/hosts.conf" <<'EOF'
[pc]
ssh = tester@pc.invalid
lanes = 2
[dead]
ssh = tester@dead.invalid
lanes = 1
EOF
# THE FAKE SSH: -O check and the -fN master succeed; the rest runs here as
# the far account. rsync calls it too (-e), with -l for user@host.
PATH_FAR="$(dirname "$REAL_TMUX"):/usr/local/bin:/usr/bin:/bin"
cat > "$SB/bin/ssh" <<EOF
#!/usr/bin/env bash
target=""; check=0
while [ \$# -gt 0 ]; do
  case "\$1" in
    -o|-p|-i|-l) shift 2 ;;
    -O) check=1; shift 2 ;;
    -*) shift ;;
    *) target="\$1"; shift; break ;;
  esac
done
case "\$target" in *dead*) echo "ssh: connect to host dead: Connection refused" >&2; exit 255 ;; esac
[ "\$check" = 1 ] && exit 0
[ \$# = 0 ] && exit 0
cmd="\$*"; H='$HOME'; X='$PC'; cmd="\${cmd//"\$H"/"\$X"}"
cd '$PC' || exit 255
exec env -i HOME='$PC' PATH='$PATH_FAR' USER=tester LANG=C.UTF-8 bash -c "\$cmd"
EOF
chmod +x "$SB/bin/ssh"

pass() { "$W" --once >/dev/null 2>&1; }
heard() { cat "$HOME/heard-$1" 2>/dev/null; }
entry() {  # entry FILE SLUG [header lines...]
  local f="$SC/$1.md" slug="$2"; shift 2
  { printf 'type: work\nat: 2026-01-01 00:00\ntitle: %s\nslug: %s\ncwd: /tmp\nstatus: pending\n' "$slug" "$slug"
    printf '%s\n' "$@"; printf -- '---\nhello from the test\n'; } > "$f"
}
field() { awk -v k="$2" '/^---$/{exit} index($0, k": ")==1{print substr($0, length(k)+3); exit}' "$1"; }

# A parent here, listening, so a report about the far lane has somewhere to go.
cat > "$SB/lane.sh" <<'EOF'
#!/bin/bash
printf '{"pid":%s,"sessionId":"sid-%s","cwd":"%s","version":"0","status":"idle","kind":"interactive","tmux":"x:@0.%s"}\n' \
  $$ "$1" "$2" "$TMUX_PANE" > "$HOME/.claude/sessions/$$.json"
cd "$2"; printf '● ready\n❯ \n'
exec cat >> "$HOME/heard-$1"
EOF
chmod +x "$SB/lane.sh"
tmux new-session -d -s claude -n home -x 220 -y 40 "sleep 900"
mkdir -p "$SB/work/orch"; tmux new-window -d -t claude: -n orch "$SB/lane.sh orch $SB/work/orch"
sleep 1
printf 'orch\t\t%s\t%s\t%s\torch.md\n' "$(tmux display-message -p -t claude:orch '#{window_id}')" \
  "$(tmux display-message -p -t claude:orch '#{pane_id}')" "$(date +%s)" >> "$ST/tree.tsv"
printf '# orch\n' > "$HO/STATUS-orch.md"
"$W" --on >/dev/null

echo "== host: pc -- the entry is handed over, not launched here"
entry pcl-1 pcl-1 "host: pc" "parent: orch"
pass
check "the entry here is launched" [ "$(field "$SC/pcl-1.md" status)" = launched ]
check "..and keeps host: pc" [ "$(field "$SC/pcl-1.md" host)" = pc ]
check "the copy is there" [ -f "$PSC/pcl-1.md" ]
check "..pending" [ "$(field "$PSC/pcl-1.md" status)" = pending ]
check "..due now (at: is a minute ago or less)" [ $(( $(date +%s) - $(date -d "$(field "$PSC/pcl-1.md" at)" +%s) )) -le 90 ]
check "..its slug pinned" [ "$(field "$PSC/pcl-1.md" slug)" = pcl-1 ]
check "..no host: there (it must not hand it back)" [ -z "$(field "$PSC/pcl-1.md" host)" ]
check "..and its body" grep -q 'hello from the test' "$PSC/pcl-1.md"
check "no window was opened here" bash -c "! tmux list-windows -t claude -F '#{window_name}' | grep -qx pcl-1"
check "the tree has the lane under orch, on pc" grep -qP '^pcl-1\torch\tpc:-\tpc:-\t' "$ST/tree.tsv"
check "the log says it was handed over" grep -q 'schedule pcl-1.md: handed to pc' "$ST/log"

echo "== the far status comes back"
# What the far watchdog would have published once it opened the window.
NOW="$(date +%s)"
printf 'sid-pcl\tpcl-1\t%s\t0\t1000\tstalled\t-\t\t-\t1234\t5678\t0\topus\t2400\t\t/tmp\t-\t0\t99999\tdone thinking\t-\n' "$FARPANE" > "$PST/status.tsv"
printf 'pcl-1\torch\t%s\t%s\t%s\tpcl-1.md\n' "$FARWID" "$FARPANE" "$NOW" > "$PST/tree.tsv"
printf '# pcl-1\nnext: nothing\n' > "$PHO/STATUS-pcl-1.md"
pass
check "its status.tsv is here" [ -f "$ST/hosts/pc/status.tsv" ]
check "the tree's pane for it is pc:%N" grep -qP "^pcl-1\torch\tpc:$FARWID\tpc:$FARPANE\t" "$ST/tree.tsv"
check "its handover reached this machine" [ -f "$HO/STATUS-pcl-1.md" ]
check "..and this one's reached it" [ -f "$PHO/STATUS-orch.md" ]
out="$("$W" --status)"
check "--status has a HOST column" grep -q $'\tTAGS\tHOST$' <<<"$out"
check "..with the far row, its SPENT and CACHED" grep -qP "^sid-pcl\tpcl-1\t$FARPANE\t.*\t1234\t5678\t.*\tpc$" <<<"$out"
check "..and this machine's rows as local" grep -qP '\tlocal$' <<<"$out"
hl="$("$W" --health 2>&1)"
check "--health names the host and its lanes" grep -q '^# host=pc lanes=2 sessions=1' <<<"$hl"
check "..and the far lane's row, with its host" grep -qE '^stalled +pcl-1 +pc +orch ' <<<"$hl"

echo "== a report about the far lane reaches its parent here"
check "orch heard that pcl-1 stalled, and where it is" grep -qE 'stalled pcl-1 \(pc claude:[0-9]+\): idle 40m' <<<"$(heard orch)"

echo "== the host's lane cap, and a host that does not answer"
sed -i 's/^lanes = 2$/lanes = 1/' "$HOME/.config/muxtopus/hosts.conf"
entry pcl-2 pcl-2 "host: pc"
pass
check "pc at its cap: held, here" [ "$(field "$SC/pcl-2.md" status)" = pending ]
check "..saying why" grep -q 'held: pc runs 1 of its 1 lanes' "$ST/sched-why.tsv"
entry dd-1 dd-1 "host: dead"
pass
check "an asleep host: held" [ "$(field "$SC/dd-1.md" status)" = pending ]
check "..saying so" grep -q 'held: dead does not answer' "$ST/sched-why.tsv"
check "..and nothing launched here for either" bash -c "! tmux list-windows -t claude -F '#{window_name}' | grep -qxE 'pcl-2|dd-1'"
rm -f "$SC/dd-1.md"

echo "== MUXTOPUS_LANE_HOST, and host: local"
sed -i 's/^lanes = 1$/lanes = 5/' "$HOME/.config/muxtopus/hosts.conf"
printf 'MUXTOPUS_LANE_HOST=pc\n' >> "$MUXTOPUS_CONFIG"
entry pcl-3 pcl-3
pass
check "no host: and MUXTOPUS_LANE_HOST=pc: handed to pc" [ -f "$PSC/pcl-3.md" ]
check "..and host: pc written here" [ "$(field "$SC/pcl-3.md" host)" = pc ]
check "pcl-2 went too, now there is room" [ -f "$PSC/pcl-2.md" ]
entry loc-1 loc-1 "host: local"
pass
check "host: local stays here, whatever the knob" [ ! -f "$PSC/loc-1.md" ]
sed -i '/^MUXTOPUS_LANE_HOST=/d' "$MUXTOPUS_CONFIG"; rm -f "$SC/loc-1.md"

echo "== a far launch that failed"
sed -i 's/^status: .*/status: error/' "$PSC/pcl-3.md"
pass
check "is this entry's failure too" [ "$(field "$SC/pcl-3.md" status)" = error ]
check "..with a log line" grep -q "schedule pcl-3.md: pc could not launch it (error)" "$ST/log"

echo "== the far ledger, in tokens-by-lane.jsonl"
cols="day session project lane model side requests in out cache_read cache_w5m cache_w1h thinking ctx_peak ctx_sum ctx_n tools web turns active_s compactions first_ts last_ts hours tool_mix coarse"
{ printf '%s\n' "${cols// /$'\t'}"
  printf '%s\tsid-pcl\t-\tpcl-1\topus\t0\t1\t10\t20\t300\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t\t\t0\n' "$(date +%F)"; } \
  > "$PC/.local/state/muxtopus/stats/ledger.tsv"
rm -f "$ST/stats.at"
pass
check "the far ledger came back" [ -f "$ST/hosts/pc/ledger.tsv" ]
check "tokens-by-lane.jsonl has the far lane, host pc, spent and cached" \
  grep -q "\"host\": \"pc\", \"slug\": \"pcl-1\", \"roadmap\": \"\", \"spent\": 30, \"cached\": 300" "$ST/tokens-by-lane.jsonl"

sb_done
