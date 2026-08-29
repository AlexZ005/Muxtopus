#!/usr/bin/env bash
# deck-status.sh -- live dashboard for parallel dev lanes on this machine.
#
#   deck-status.sh          live, refreshing every 2s   (q quits, r refreshes)
#   deck-status.sh --once   render once and exit        (for scripts/pipes)
#   deck-status.sh --int N  refresh every N seconds
#
# Designed to be the landing window of the shared tmux session, so attaching
# shows the state of the machine before anything else.
#
# A dev server is a PROCESS GROUP, not a process: `npm run dev` and the vite
# it spawns are separate, and the port belongs to vite while npm holds its own
# ~70 MB. Everything here therefore aggregates by PGID, which is also what
# makes the per-lane totals honest.
set -uo pipefail

INTERVAL=2
ONCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --once)  ONCE=1; shift ;;
    --int)   INTERVAL="${2:-2}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

C_RST=$'\033[0m'; C_B=$'\033[1m'; C_DIM=$'\033[90m'
C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_CYA=$'\033[36m'

hr() { printf '%s%s%s\n' "$C_DIM" "$(printf '%*s' "${COLS:-72}" '' | tr ' ' '-')" "$C_RST"; }
head2() { printf '\n%s%s%s\n' "$C_B" "$1" "$C_RST"; }

human_mb() { # MB -> "1.2 GB" or "812 MB"
  local mb=$1
  if [ "$mb" -ge 1024 ]; then awk -v m="$mb" 'BEGIN{printf "%.1f GB", m/1024}'
  else printf '%s MB' "$mb"; fi
}

dur() { # seconds -> compact age
  local s=$1
  if   [ "$s" -ge 86400 ]; then printf '%dd' $((s/86400))
  elif [ "$s" -ge 3600 ];  then printf '%dh' $((s/3600))
  elif [ "$s" -ge 60 ];    then printf '%dm' $((s/60))
  else printf '%ds' "$s"; fi
}

bar() { # used_pct width -> coloured bar
  local pct=$1 w=${2:-18} filled c
  filled=$(( pct * w / 100 )); [ "$filled" -gt "$w" ] && filled=$w
  if   [ "$pct" -ge 90 ]; then c=$C_RED
  elif [ "$pct" -ge 70 ]; then c=$C_YEL
  else c=$C_GRN; fi
  printf '%s%s%s%s' "$c" "$(printf '%*s' "$filled" '' | tr ' ' '#')" "$C_DIM" "$(printf '%*s' $((w-filled)) '' | tr ' ' '.')$C_RST"
}

lane_of() { # pid -> short lane name from its cwd
  local cwd; cwd=$(readlink "/proc/$1/cwd" 2>/dev/null) || return 1
  case "$cwd" in
    "$HOME/.code/"*) printf '%s' "${cwd#$HOME/.code/}" ;;
    "$HOME/"*)       printf '~/%s' "${cwd#$HOME/}" ;;
    *)               printf '%s' "$cwd" ;;
  esac
}

render() {
  COLS=$(tput cols 2>/dev/null || echo 72)
  [ "$COLS" -gt 100 ] && COLS=100
  local now total avail used pct swtot swused load cores temp cap st

  now=$(date '+%H:%M:%S')
  read -r total avail < <(awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{printf "%.1f %.1f", t/1048576, a/1048576}' /proc/meminfo)
  used=$(awk -v t="$total" -v a="$avail" 'BEGIN{printf "%.1f", t-a}')
  pct=$(awk -v t="$total" -v a="$avail" 'BEGIN{printf "%d", (t-a)*100/t}')
  read -r swtot swused < <(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{printf "%.1f %.1f", t/1048576, (t-f)/1048576}' /proc/meminfo)
  load=$(awk '{print $1}' /proc/loadavg)
  cores=$(nproc 2>/dev/null || echo 1)
  temp=$(for z in /sys/class/thermal/thermal_zone*/temp; do cat "$z" 2>/dev/null; done | sort -rn | head -1 | awk '{printf "%.0f", $1/1000}')
  cap=$(cat /sys/class/power_supply/BAT*/capacity 2>/dev/null | head -1)
  st=$(cat /sys/class/power_supply/BAT*/status 2>/dev/null | head -1)

  printf '%s DECK%s  %s  %sup %s%s  %s%s%s\n' "$C_B" "$C_RST" \
    "$(uname -n)" "$C_DIM" "$(uptime -p 2>/dev/null | sed 's/^up //')" "$C_RST" "$C_DIM" "$now" "$C_RST"
  hr
  printf '  %-8s %s  %s%5.1f%s of %s GiB free   %s%s%% used%s\n' \
    "MEMORY" "$(bar "$pct")" "$C_B" "$avail" "$C_RST" "$total" "$C_DIM" "$pct" "$C_RST"
  printf '  %-8s %s GiB of %s GiB (zram)\n' "SWAP" "$swused" "$swtot"
  printf '  %-8s load %s over %s threads   %s C   battery %s%% %s\n' \
    "CPU" "$load" "$cores" "${temp:-?}" "${cap:-?}" "${st:-?}"

  # ---- dev servers, aggregated by process group -------------------------
  declare -A IS_SRV SRV_RSS SRV_AGE SRV_PID SRV_PORT
  local pid pgid et rss args srv_found=0
  while read -r pid pgid et rss args; do
    case "$args" in
      *node_modules/.bin/vite*|*"vite dev"*|*"npm run dev"*|*"npm exec vite"*)
        if [ -z "${IS_SRV[$pgid]:-}" ]; then IS_SRV[$pgid]=1; srv_found=$((srv_found+1)); fi
        # prefer the vite process for cwd: npm's cwd is the same, but vite is
        # the one that actually owns the port.
        if [ -z "${SRV_PID[$pgid]:-}" ] || [ "${args#*vite}" != "$args" ]; then
          SRV_PID[$pgid]=$pid
        fi
        [ "${SRV_AGE[$pgid]:-0}" -lt "$et" ] && SRV_AGE[$pgid]=$et
        ;;
    esac
  done < <(ps -eo pid,pgid,etimes,rss,args --no-headers 2>/dev/null)

  local total_srv_mb=0 nsrv=0 rows=""
  if [ "$srv_found" -gt 0 ]; then
    # sum EVERY process in each server's group, not just the matching ones
    while read -r pid pgid et rss args; do
      [ -n "${IS_SRV[$pgid]:-}" ] && SRV_RSS[$pgid]=$(( ${SRV_RSS[$pgid]:-0} + rss ))
    done < <(ps -eo pid,pgid,etimes,rss,args --no-headers 2>/dev/null)

    # map listening ports to those groups, one socket line at a time
    local lline lport lpid lpg
    while read -r lline; do
      [ -z "$lline" ] && continue
      lport=$(printf '%s' "$lline" | awk '{print $4}' | sed 's/.*://')
      lpid=$(printf '%s' "$lline" | grep -oP 'pid=\K[0-9]+' | head -1)
      [ -z "$lpid" ] && continue
      lpg=$(ps -o pgid= -p "$lpid" 2>/dev/null | tr -d ' ')
      [ -n "$lpg" ] && [ -n "${IS_SRV[$lpg]:-}" ] && SRV_PORT[$lpg]="$lport"
    done < <(ss -lptnH 2>/dev/null)
  fi

  head2 "DEV SERVERS"
  if [ "$srv_found" -eq 0 ]; then
    printf '  %snone running%s\n' "$C_DIM" "$C_RST"
  else
    # Totals are accumulated HERE, not inside the print pipeline: a `| sort`
    # runs in a subshell and every increment made there is discarded.
    local mb age_c
    for pgid in "${!IS_SRV[@]}"; do
      mb=$(( ${SRV_RSS[$pgid]:-0} / 1024 ))
      total_srv_mb=$(( total_srv_mb + mb ))
      nsrv=$(( nsrv + 1 ))
      age_c=""
      [ "${SRV_AGE[$pgid]:-0}" -ge 86400 ] && age_c=1
      rows+=$(printf '  %-7s %9s %s%6s%s  %s' \
        "${SRV_PORT[$pgid]:-?}" "$(human_mb "$mb")" \
        "${age_c:+$C_YEL}" "$(dur "${SRV_AGE[$pgid]:-0}")" "${age_c:+$C_RST}" \
        "$(lane_of "${SRV_PID[$pgid]}" 2>/dev/null || echo '?')")$'\n'
    done
    printf '  %s%-7s %9s %6s  %s%s\n' "$C_DIM" "PORT" "RAM" "UP" "LANE" "$C_RST"
    printf '%s' "$rows" | sort -n
    printf '  %s%-7s %9s%s  %s%s server(s)%s\n' \
      "$C_B" "TOTAL" "$(human_mb "$total_srv_mb")" "$C_RST" "$C_DIM" "$nsrv" "$C_RST"
    printf '  %s(a vite server grows with age - restart one past ~1 day)%s\n' "$C_DIM" "$C_RST"
  fi

  # ---- other workloads ---------------------------------------------------
  head2 "OTHER"
  local cl_n cl_mb
  cl_n=$(pgrep -cx claude 2>/dev/null | head -1); cl_n=${cl_n:-0}
  cl_mb=$(ps -eo rss,comm --no-headers 2>/dev/null | awk '$2=="claude"{s+=$1}END{printf "%d", s/1024}')
  printf '  %-10s %s session(s), %s\n' "claude" "$cl_n" "$(human_mb "${cl_mb:-0}")"
  local br_mb; br_mb=$(ps -eo rss,args --no-headers 2>/dev/null | grep -F 'ms-playwright' | grep -v grep | awk '{s+=$1}END{printf "%d", s/1024}')
  [ "${br_mb:-0}" -gt 0 ] && printf '  %-10s %s\n' "playwright" "$(human_mb "$br_mb")"
  printf '  %-10s %s free on /home\n' "disk" "$(df -h /home --output=avail 2>/dev/null | tail -1 | tr -d ' ')"

  hr
  printf ' %sq quit   r refresh   Ctrl-b 1 -> Claude   every %ss%s\n' "$C_DIM" "$INTERVAL" "$C_RST"
}

if [ "$ONCE" = 1 ] || [ ! -t 1 ]; then render; exit 0; fi

trap 'printf "\033[?25h\n"; exit 0' INT TERM
printf '\033[?25l'                     # hide cursor
while :; do
  printf '\033[H\033[J'                # home + clear
  render
  if [ -t 0 ]; then read -rsn1 -t "$INTERVAL" key || true; else key=""; sleep "$INTERVAL"; fi
  case "${key:-}" in
    q|Q) break ;;
  esac
done
printf '\033[?25h'
