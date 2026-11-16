byond_topic() {
sh -s -- "$@" <<'SH'
# POSIX utilities and nc. Exit: 0 value, 1 error, 2 null, 124 timeout.
set -ef
export LC_ALL=C
die() { printf '%s\n' "$*" >&2; exit 1; }
[ "$#" -eq 3 ] || die "Usage: $0 <address> <port> <message>"
case $1 in ''|-*) die 'Invalid address' ;; esac
case $2 in ''|*[!0-9]*) die 'Invalid port' ;; esac
[ "$2" -ge 1 ] && [ "$2" -le 65535 ] || die 'Invalid port'
q=?${3#\?}; n=$((${#q}+6))
[ "$n" -lt 65536 ] || die 'Query exceeds two-byte frame length'
command -v nc >/dev/null 2>&1 || die 'nc is required'
umask 077
work=${TMPDIR:-/tmp}/byond-wire.$$
mkdir "$work"
network= timer= io=
cleanup() {
  kill $io $timer $network 2>/dev/null || :
  wait
  rm -rf "$work"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
trap 'printf "%s\n" "Topic request timed out" >&2; exit 124' ALRM
printf '\000\203%b\000\000\000\000\000%s\000' \
  "$(printf '\\0%03o\\0%03o' "$((n/256))" "$((n%256))")" "$q" >"$work/request"
mkfifo "$work/reply"
nc "$1" "$2" <"$work/request" >"$work/reply" & network=$!
(
  trap 'kill ${sleeper-} 2>/dev/null || :; exit' HUP INT TERM
  sleep 5 & sleeper=$!
  wait "$sleeper"
  kill -s ALRM "$$"
  kill "$network" 2>/dev/null || :
) & timer=$!
exec 3<"$work/reply"
copy() { dd ibs=1 obs=65536 "$@" <&3 2>/dev/null & io=$!; wait "$io"; io=; }
get() {
  copy count="$1" >"$work/body"
  [ "$(wc -c <"$work/body")" -eq "$1" ] || die 'Incomplete Topic response'
}
get 4
set -- $(od -An -v -t u1 "$work/body")
[ "$1:$2" = 0:131 ] || die 'Non-Topic response'
n=$(($3*256+$4))
[ "$n" -gt 0 ] || die 'Empty Topic body'
get "$n"
set -- $(od -An -N 1 -t u1 "$work/body")
case $1:$n in
  0:1) exit 2 ;;
  6:*) [ "$n" -ge 2 ] || die 'Invalid text response'
    set -- $(od -An -j "$((n-1))" -t u1 "$work/body")
    [ "$1" -eq 0 ] || die 'Invalid text response'
    copy skip=1 count="$((n-2))" 3<"$work/body" ;;
  42:5) if [ "$(printf '\001\000' | od -An -t u2)" -ne 1 ]; then
      set -- $(od -An -j 1 -t u1 "$work/body")
      printf '\052%b' "$(printf '\\0%03o' "$4" "$3" "$2" "$1")" >"$work/body"
    fi
    set -- $(od -An -j 1 -t f4 "$work/body")
    printf '%s' "$1" ;;
  *) die 'Invalid Topic response' ;;
esac
SH
}

byond_decode_text() (
  export LC_ALL=C
  bytes=$(od -An -v -t o1) || exit 1
  bytes=$(printf '%s' "$bytes" | tr -d '[:space:]') || exit 1
  # Octal byte ranges keep NULs out of shell variables. Match UTF-8 and markers atomically.
  cont='2[0-7][0-7]'
  marker='377(00[67]|01[01]|022|02[5-7]|03[017]|04[0-6])'
  utf8="[01][0-7][0-7]|3(0[2-7]|[1-3][0-7])$cont"
  utf8="$utf8|3402[4-7][0-7]$cont|3(4[1-7]|5[0-467])$cont$cont|3552[0-3][0-7]$cont"
  utf8="$utf8|3602[2-7][0-7]$cont$cont|36[1-3]$cont$cont$cont|3642[01][0-7]$cont$cont"
  printf '%s\n' "$bytes" | grep -Eq "^($utf8|$marker)*$" || {
    printf '%s\n' 'Invalid UTF-8 or BYOND text marker' >&2; exit 1;
  }
  out=$(printf '%s' "$bytes" | sed 's/377...//g;s/.../\\0&/g') || exit 1
  printf '%b' "$out"
)
