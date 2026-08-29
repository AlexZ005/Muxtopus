#!/usr/bin/env bash
# deck-status.sh -- live dashboard for parallel dev lanes.
#
#   deck-status.sh            live      (q quit / r refresh / s,S extras / ? help)
#   deck-status.sh --once     one frame and exit
#   deck-status.sh --int N    refresh every N seconds (default 2)
#
# WHY PLAIN ANSI AND NO TUI LIBRARY
#   Rich/Textual were evaluated and do work here -- a venv installs cleanly --
#   but a venv is pinned to python3.13, and a SteamOS update that moves Python
#   breaks it. This is the thing you open WHEN something is broken, so it must
#   never be the broken thing. Raw ECMA-48 has no runtime, starts instantly and
#   survives A/B updates by construction.
#
# WHY IT DOES NOT FLICKER
#   The whole frame is composed in memory and emitted in ONE write, homed with
#   ESC[H, every line terminated with ESC[K (erase to end of line), the frame
#   closed with ESC[J. Nothing is cleared before drawing: a clear-then-draw
#   cycle is precisely what makes a terminal blink.
set -uo pipefail

# The frame maths counts CHARACTERS, so a UTF-8 locale is REQUIRED. Under
# POSIX, bash's ${#s} counts BYTES -- each sparkline glyph is three of them --
# so every framed row came up short of its own border. Measured on this box:
# the string of three block glyphs is 9 under POSIX and 3 under C.UTF-8.
# SSH does not forward a locale here (LC_CTYPE arrives as POSIX), so set one.
if [ -z "${LC_ALL:-}" ]; then
  if locale -a 2>/dev/null | grep -qx 'C.utf8'; then
    export LC_ALL=C.utf8
  else
    _u=$(locale -a 2>/dev/null | grep -iE 'utf-?8' | head -1)
    [ -n "$_u" ] && export LC_ALL="$_u"
  fi
fi

INTERVAL=2; ONCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --once) ONCE=1; shift ;;
    --int)  INTERVAL="${2:-2}"; shift 2 ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

E=$'\033'
R="${E}[0m"; B="${E}[1m"; D="${E}[38;5;244m"
GRN="${E}[38;5;114m"; YEL="${E}[38;5;179m"; RED="${E}[38;5;167m"
CYA="${E}[38;5;110m"; MAG="${E}[38;5;140m"; FRM="${E}[38;5;238m"

SPARK=($'▁' $'▂' $'▃' $'▄' $'▅' $'▆' $'▇' $'█')
declare -a PREV_IDLE PREV_TOT
NOTICE=""; NOTICE_AT=0
FRAME=""; W=78; COLS=80
VER=$(cat "$(dirname "$(readlink -f "$0")")/VERSION" 2>/dev/null || echo "?")

vislen() { local s; s=$(printf '%s' "$1" | sed "s/${E}\[[0-9;]*m//g"); printf '%s' "${#s}"; }

pad() { local v; v=$(vislen "$1"); printf '%s%*s' "$1" $(( W > v ? W - v : 0 )) ''; }
row() { FRAME+="${FRM}|${R}$(pad "$1")${FRM}|${R}${E}[K"$'\n'; }
rule() { printf '%*s' "$1" '' | tr ' ' '-'; }
top() { local t=" $1 " l; l=$(( W - $(vislen "$t") - 1 ))
        [ "$l" -lt 0 ] && l=0
        FRAME+="${FRM}+-${R}${B}${t}${R}${FRM}$(rule "$l")+${R}${E}[K"$'\n'; }
bot() { FRAME+="${FRM}+$(rule "$W")+${R}${E}[K"$'\n'; }

gauge() {
  local p=$1 w=$2 f c
  f=$(( p * w / 100 )); [ "$f" -gt "$w" ] && f=$w; [ "$f" -lt 0 ] && f=0
  if   [ "$p" -ge 90 ]; then c=$RED; elif [ "$p" -ge 70 ]; then c=$YEL; else c=$GRN; fi
  printf '%s%s%s%s%s' "$c" "$(printf '%*s' "$f" '' | tr ' ' '#')" \
         "$D" "$(printf '%*s' $((w-f)) '' | tr ' ' '.')" "$R"
}

cpu_spark() {
  local i=0 out="" line idle tot busy pct lvl v pi pt
  while read -r line; do
    case "$line" in cpu[0-9]*) ;; *) continue ;; esac
    set -- $line
    shift
    idle=$4; tot=0
    for v in "$@"; do tot=$(( tot + v )); done
    pi=${PREV_IDLE[$i]:-0}; pt=${PREV_TOT[$i]:-0}
    if [ "$pt" -gt 0 ] && [ "$tot" -gt "$pt" ]; then
      busy=$(( (tot - pt) - (idle - pi) ))
      pct=$(( busy * 100 / (tot - pt) ))
    else
      pct=0
    fi
    [ "$pct" -lt 0 ] && pct=0
    [ "$pct" -gt 100 ] && pct=100
    lvl=$(( pct * 7 / 100 ))
    if   [ "$pct" -ge 80 ]; then out+="${RED}${SPARK[$lvl]}"
    elif [ "$pct" -ge 45 ]; then out+="${YEL}${SPARK[$lvl]}"
    else out+="${GRN}${SPARK[$lvl]}"; fi
    PREV_IDLE[$i]=$idle; PREV_TOT[$i]=$tot
    i=$(( i + 1 ))
  done < /proc/stat
  printf '%s%s' "$out" "$R"
}

human_mb() { local m=$1
  if [ "$m" -ge 1024 ]; then awk -v m="$m" 'BEGIN{printf "%.1f GB", m/1024}'
  else printf '%d MB' "$m"; fi; }

dur() { local s=$1
  if   [ "$s" -ge 86400 ]; then printf '%dd' $(( s / 86400 ))
  elif [ "$s" -ge 3600 ];  then printf '%dh' $(( s / 3600 ))
  elif [ "$s" -ge 60 ];    then printf '%dm' $(( s / 60 ))
  else printf '%ds' "$s"; fi; }

lane_of() { local c
  c=$(readlink "/proc/$1/cwd" 2>/dev/null) || return 1
  case "$c" in
    "$HOME/.code/"*) printf '%s' "${c#"$HOME"/.code/}" ;;
    "$HOME/"*)       printf '~/%s' "${c#"$HOME"/}" ;;
    *)               printf '%s' "$c" ;;
  esac; }

compose() {
  COLS=$(tput cols 2>/dev/null || echo 100)
  [ "$COLS" -gt 160 ] && COLS=160
  [ "$COLS" -lt 64 ] && COLS=64
  W=$(( COLS - 2 ))
  FRAME=""

  local total avail pct swt swu load cores temp cap st mode
  read -r total avail < <(awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{printf "%.1f %.1f", t/1048576, a/1048576}' /proc/meminfo)
  pct=$(awk -v t="$total" -v a="$avail" 'BEGIN{printf "%d",(t-a)*100/t}')
  read -r swt swu < <(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{printf "%.1f %.1f", t/1048576,(t-f)/1048576}' /proc/meminfo)
  load=$(awk '{print $1}' /proc/loadavg)
  cores=$(nproc 2>/dev/null || echo 1)
  temp=$(for z in /sys/class/thermal/thermal_zone*/temp; do cat "$z" 2>/dev/null; done | sort -rn | head -1 | awk '{printf "%.0f",$1/1000}')
  cap=$(cat /sys/class/power_supply/BAT*/capacity 2>/dev/null | head -1)
  st=$(cat /sys/class/power_supply/BAT*/status 2>/dev/null | head -1)
  case "$st" in
    Charging)    st="chg" ;;
    Discharging) st="bat" ;;
    *)           st="ac"  ;;
  esac
  if   pgrep -x kwin_wayland >/dev/null 2>&1; then mode=desktop
  elif pgrep -f start-gamescope-session >/dev/null 2>&1; then mode=game
  else mode="?"; fi

  top "deck"
  row "  ${D}$(uname -n) . ${cores} threads . ${mode} mode${R}${D} . v${VER}${R}"
  row "  ${B}MEM${R}  $(gauge "$pct" 24)  ${B}${avail}${R} of ${total} GiB free   ${D}${pct}% used${R}"
  row "  ${B}SWP${R}  ${D}${swu} of ${swt} GiB zram${R}"
  row "  ${B}CPU${R}  $(cpu_spark)  ${D}load${R} ${load}   ${D}${temp}C${R}   ${D}${st}${R} ${cap}%"
  bot

  declare -A SRV RSS AGE PID PORT
  local pid pgid et rss args n=0
  while read -r pid pgid et rss args; do
    case "$args" in
      *node_modules/.bin/vite*|*"vite dev"*|*"npm run dev"*|*"npm exec vite"*)
        if [ -z "${SRV[$pgid]:-}" ]; then SRV[$pgid]=1; n=$(( n + 1 )); fi
        if [ -z "${PID[$pgid]:-}" ] || [ "${args#*vite}" != "$args" ]; then PID[$pgid]=$pid; fi
        [ "${AGE[$pgid]:-0}" -lt "$et" ] && AGE[$pgid]=$et
        ;;
    esac
  done < <(ps -eo pid,pgid,etimes,rss,args --no-headers 2>/dev/null)

  local tot_mb=0
  if [ "$n" -gt 0 ]; then
    while read -r pid pgid et rss args; do
      [ -n "${SRV[$pgid]:-}" ] && RSS[$pgid]=$(( ${RSS[$pgid]:-0} + rss ))
    done < <(ps -eo pid,pgid,etimes,rss,args --no-headers 2>/dev/null)
    local ll lp lpid lpg
    while read -r ll; do
      [ -z "$ll" ] && continue
      lp=$(printf '%s' "$ll" | awk '{print $4}' | sed 's/.*://')
      lpid=$(printf '%s' "$ll" | grep -oP 'pid=\K[0-9]+' | head -1)
      [ -z "$lpid" ] && continue
      lpg=$(ps -o pgid= -p "$lpid" 2>/dev/null | tr -d ' ')
      if [ -n "$lpg" ] && [ -n "${SRV[$lpg]:-}" ]; then PORT[$lpg]="$lp"; fi
    done < <(ss -lptnH 2>/dev/null)
    for pgid in "${!SRV[@]}"; do tot_mb=$(( tot_mb + ${RSS[$pgid]:-0} / 1024 )); done
  fi

  top "lanes${D} . ${n} server(s) . $(human_mb "$tot_mb")${R}${FRM}"
  if [ "$n" -eq 0 ]; then
    row "  ${D}no dev servers running${R}"
  else
    row "  ${D}$(printf '%-6s %10s %7s  %-30s %s' PORT RAM AGE LANE STATE)${R}"
    local rows="" mb age ac state l
    for pgid in "${!SRV[@]}"; do
      mb=$(( ${RSS[$pgid]:-0} / 1024 )); age=${AGE[$pgid]:-0}
      if   [ "$age" -ge 86400 ]; then ac=$RED; state="${RED}stale, restart${R}"
      elif [ "$age" -ge 21600 ]; then ac=$YEL; state="${YEL}ageing${R}"
      else ac=$GRN; state="${GRN}fresh${R}"; fi
      rows+="$(printf '  %s%-6s%s %10s %s%7s%s  %-30s %s' \
        "$CYA" "${PORT[$pgid]:-?}" "$R" "$(human_mb "$mb")" \
        "$ac" "$(dur "$age")" "$R" \
        "$(lane_of "${PID[$pgid]}" 2>/dev/null || echo '?')" "$state")"$'\n'
    done
    while IFS= read -r l; do
      [ -n "$l" ] && row "$l"
    done < <(printf '%s' "$rows" | sort -k2 -n)
  fi
  bot

  local cn cm pw dsk ex pws
  cn=$(pgrep -cx claude 2>/dev/null | head -1); cn=${cn:-0}
  cm=$(ps -eo rss,comm --no-headers 2>/dev/null | awk '$2=="claude"{s+=$1}END{printf "%d",s/1024}')
  pw=$(ps -eo rss,args --no-headers 2>/dev/null | grep -F ms-playwright | grep -v grep | awk '{s+=$1}END{printf "%d",s/1024}')
  dsk=$(df -h /home --output=avail 2>/dev/null | tail -1 | tr -d ' ')
  ex=$(ps -eo rss,args --no-headers 2>/dev/null | grep -E 'plasmashell|plasma-discover|steamwebhelper|Steam/ubuntu12_32' | grep -v grep | awk '{s+=$1}END{printf "%d",s/1024}')
  if [ "${pw:-0}" -gt 0 ]; then pws=$(human_mb "$pw"); else pws="${D}-${R}"; fi

  top "system"
  row "  ${B}claude${R} ${cn} . $(human_mb "${cm:-0}")     ${B}playwright${R} ${pws}     ${B}/home${R} ${dsk} free"
  row "  ${B}desktop extras${R} $(human_mb "${ex:-0}")  ${D}reclaimable with s, desktop mode only${R}"
  bot

  if [ -n "$NOTICE" ] && [ $(( $(date +%s) - NOTICE_AT )) -lt 8 ]; then
    FRAME+=" ${MAG}${NOTICE}${R}${E}[K"$'\n'
  else
    FRAME+="${E}[K"$'\n'
  fi
  FRAME+=" ${D}q${R} quit  ${D}r${R} refresh  ${D}R${R} reload  ${D}s${R} stop extras  ${D}S${R} start  ${D}p${R} btop  ${D}?${R} help${E}[K"$'\n'
  FRAME+="${E}[J"
}

paint() { compose; printf '%s%s' "${E}[H" "$FRAME"; }

notice_from() {
  NOTICE=$("$@" 2>&1 | sed "s/${E}\[[0-9;]*m//g" | grep -E '^[[:space:]]+[+!.]' | tail -1 | sed 's/^[[:space:]]*//')
  [ -z "$NOTICE" ] && NOTICE="done"
  NOTICE_AT=$(date +%s)
}

helpscreen() {
  printf '%s%s' "${E}[H" "${E}[J"
  printf '\n  %sdeck-status%s -- lane dashboard\n\n' "$B" "$R"
  printf '  %sq%s quit        %sr%s redraw now\n' "$B" "$R" "$B" "$R"
  printf '  %ss%s stop extras %sS%s start extras   (deck-ram.sh, desktop mode only)\n' "$B" "$R" "$B" "$R"
  printf '  %sp%s btop        %s?%s this screen\n\n' "$B" "$R" "$B" "$R"
  printf '  %sLANE STATE%s\n' "$D" "$R"
  printf '    %sfresh%s    under 6h\n' "$GRN" "$R"
  printf '    %sageing%s   6-24h\n' "$YEL" "$R"
  printf '    %sstale%s    over 24h. A vite server was measured at 2487 MB after\n' "$RED" "$R"
  printf '             three days against 1142 MB fresh, and a long-lived server\n'
  printf '             is also what serves dual module instances.\n\n'
  printf '  %sRAM is summed per PROCESS GROUP: npm run dev and the vite it spawns\n' "$D"
  printf '  are separate processes, the port belongs to vite, and npm holds ~70 MB\n'
  printf '  of its own.%s\n\n' "$R"
  printf '  %spress any key%s\n' "$D" "$R"
  read -rsn1 -t 60 || true
}

if [ "$ONCE" = 1 ] || [ ! -t 1 ]; then
  compose
  printf '%s' "$FRAME"
  exit 0
fi

cleanup() { printf '%s%s' "${E}[?25h" "${E}[?1049l"; exit 0; }
trap cleanup INT TERM EXIT
printf '%s%s' "${E}[?1049h" "${E}[?25l"

compose >/dev/null    # prime CPU deltas so the first visible frame is real
while :; do
  paint
  if [ -t 0 ]; then
    read -rsn1 -t "$INTERVAL" k || true
  else
    k=""; sleep "$INTERVAL"
  fi
  case "${k:-}" in
    q|Q) break ;;
    r)   : ;;
    # A running pane holds the copy it started with, so re-exec to pick
    # up an edited script without respawning the tmux window.
    R)   exec "$0" --int "$INTERVAL" ;;
    '?') helpscreen ;;
    p|P) printf '%s' "${E}[?1049l"; btop 2>/dev/null || htop 2>/dev/null || true; printf '%s' "${E}[?1049h" ;;
    s)   NOTICE="stopping desktop extras..."; NOTICE_AT=$(date +%s); paint
         notice_from "$HOME/.code/scripts/deck-ram.sh" stop ;;
    S)   NOTICE="starting desktop extras..."; NOTICE_AT=$(date +%s); paint
         notice_from "$HOME/.code/scripts/deck-ram.sh" start ;;
  esac
done
