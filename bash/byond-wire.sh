byond_topic() (
# GNU coreutils. Exit: 0 value, 1 error, 2 null, 124 timeout.
[[ $# == 3 ]] || { printf 'Usage: %s <address> <port> <message>\n' "$0" >&2; exit 1; }
exec timeout 5 bash -s -- "$@" <<'BASH'
set -eo pipefail
export LC_ALL=C
die() { printf '%s\n' "$*" >&2; exit 1; }
[[ $1 && $1 != -* ]] || die 'Invalid address'
port=${2#"${2%%[!0]*}"}
[[ $port && $port != *[!0-9]* && ${#port} -le 5 ]] && ((10#$port <= 65535)) || die 'Invalid port'
q=?${3#\?}; n=$((${#q}+6))
((n < 65536)) || die 'Query exceeds two-byte frame length'
printf -v h '%04x' "$n"
body=$(mktemp)
trap 'rm -f -- "$body"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Stage binary bytes so printf cannot flush a partial request at a newline.
printf '\0\203%b\0\0\0\0\0%s\0' "\\x${h:0:2}\\x${h:2}" "$q" >"$body"
exec 3<>"/dev/tcp/$1/$port"
cat "$body" >&3
b=($(dd bs=4 count=1 iflag=fullblock status=none <&3 | od -An -tu1))
((${#b[@]} == 4)) || die 'Incomplete Topic response'
[[ ${b[0]}:${b[1]} == 0:131 ]] || die 'Non-Topic response'
n=$((b[2]*256+b[3]))
((n)) || die 'Empty Topic body'
dd bs="$n" count=1 iflag=fullblock status=none <&3 >"$body"
[[ $(wc -c <"$body") == "$n" ]] || die 'Incomplete Topic response'
tag=$(od -An -N1 -tu1 "$body")
case ${tag//[[:space:]]/}:$n in
  0:1) exit 2 ;;
  6:*) ((n >= 2)) || die 'Invalid text response'
    last=$(od -An -j "$((n-1))" -tu1 "$body")
    ((last == 0)) || die 'Invalid text response'
    dd iflag=skip_bytes,count_bytes skip=1 count="$((n-2))" status=none <"$body" ;;
  42:5) v=$(od -An -j1 --endian=little -tf4 "$body")
    printf '%s' "${v//[[:space:]]/}" ;;
  *) die 'Invalid Topic response' ;;
esac
BASH
)

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
