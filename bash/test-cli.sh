#!/bin/bash
# Local wire-level regression tests; requires socat and GNU coreutils.
set -u
CLIENT_SHELL=${CLIENT_SHELL:-bash}
CLIENT_SCRIPT=${CLIENT_SCRIPT:-./cli.sh}
cd -- "$(dirname -- "$0")"
if [[ ${1-} == --serve ]]; then
  timeout .2 cat > "$REQUEST_FILE" || :
  [[ ${STALL-} != 1 ]] || { sleep 6; exit; }
  if [[ ${FRAGMENT-} == 1 ]]; then
    for ((i=0; i<${#REPLY_BYTES}; i+=4)); do
      printf '%b' "${REPLY_BYTES:i:4}"
      sleep .002
    done
  else
    printf '%b' "$REPLY_BYTES"
  fi
  [[ ${HOLD_OPEN-} != 1 ]] || sleep 6
  exit
fi
[[ -f $CLIENT_SCRIPT ]] || { printf 'FAIL client does not exist: %s\n' "$CLIENT_SCRIPT"; exit 1; }
work=$(mktemp -d)
mkdir "$work/client-tmp"
export TMPDIR="$work/client-tmp"
server=
trap '[[ -z $server ]] || kill "$server" 2>/dev/null; rm -rf -- "$work"' EXIT
failures=0
check() {
  local name=$1 query=$2 expected=$4 code=$5 port actual status
  export REPLY_BYTES=$3 REQUEST_FILE="$work/request"
  : >"$work/server.log"
  socat -d -d TCP-LISTEN:0,bind=127.0.0.1 EXEC:"bash '$PWD/test-cli.sh' --serve" 2>"$work/server.log" &
  server=$!
  port=
  for ((attempt=0; attempt<200; attempt++)); do
    if [[ $(cat "$work/server.log") =~ 127.0.0.1:([0-9]+) ]]; then
      port=${BASH_REMATCH[1]}
      break
    fi
    sleep .01
  done
  [[ -n $port ]] || { cat "$work/server.log"; exit 1; }
  if [[ ${BLOCK_OUTPUT-} == 1 ]]; then
    mkfifo "$work/blocked"
    sleep 9 <"$work/blocked" &
    local consumer=$!
    dd if=/dev/zero bs=4096 count=1 status=none >"$work/blocked"
    timeout -s KILL 8 "$CLIENT_SHELL" "$CLIENT_SCRIPT" 127.0.0.1 "$port" "$query" >"$work/blocked" 2>"$work/err"
    status=$?
    kill "$consumer" 2>/dev/null || :
    wait "$consumer" 2>/dev/null || :
    rm "$work/blocked"
    : >"$work/out"
  else
    "$CLIENT_SHELL" "$CLIENT_SCRIPT" 127.0.0.1 "$port" "$query" >"$work/out" 2>"$work/err"
    status=$?
  fi
  wait "$server" || :
  server=
  if [[ -n ${EXPECTED_FILE-} ]]; then
    cp "$EXPECTED_FILE" "$work/expected"
  else
    printf '%s' "$expected" >"$work/expected"
  fi
  if [[ -n $(ls -A "$TMPDIR") ]]; then
    printf 'FAIL %s temporary files leaked\n' "$name"
    ((failures+=1))
  fi
  if [[ $status == "$code" ]] && cmp -s "$work/out" "$work/expected"; then
    printf 'PASS %s\n' "$name"
  else
    printf 'FAIL %s (exit %s, expected %s; output hex: %s)\n' "$name" "$status" "$code" "$(od -An -v -t x1 "$work/out")"
    ((failures+=1))
  fi
  [[ $query == \?* ]] || query="?$query"
  printf '%s\0' "$query" >"$work/expected-query"
  dd bs=1 skip=9 status=none <"$work/request" >"$work/query"
  printf '\0\0\0\0\0' >"$work/expected-prefix"
  dd bs=1 skip=4 count=5 status=none <"$work/request" >"$work/prefix"
  local header=($(od -An -N4 -t u1 "$work/request"))
  actual=$(wc -c <"$work/request")
  if ! cmp -s "$work/prefix" "$work/expected-prefix" ||
     ! cmp -s "$work/query" "$work/expected-query" ||
     [[ ${header[0]-} != 0 || ${header[1]-} != 131 ]] ||
     (( ${header[2]:-0} * 256 + ${header[3]:-0} != actual - 4 )); then
    printf 'FAIL %s request bytes/length\n' "$name"
    ((failures+=1))
  fi
}
# Invalid endpoints must fail validation, before DNS or a TCP connection.
for port in 0 -1 65536 111743 1.5 http 0x50 999999999999999999999999999999; do
  "$CLIENT_SHELL" "$CLIENT_SCRIPT" 127.0.0.1 "$port" status >"$work/out" 2>"$work/err"
  status=$?
  if [[ $status != 1 || -s $work/out ]] || ! grep -q 'Invalid port' "$work/err"; then
    printf 'FAIL invalid port %s (exit %s)\n' "$port" "$status"
    ((failures+=1))
  fi
done
for address in '' '-invalid'; do
  "$CLIENT_SHELL" "$CLIENT_SCRIPT" "$address" 4999 status >"$work/out" 2>"$work/err"
  status=$?
  if [[ $status != 1 || -s $work/out ]] || ! grep -q 'Invalid address' "$work/err"; then
    printf 'FAIL invalid address %s (exit %s)\n' "$address" "$status"
    ((failures+=1))
  fi
done
check short-text who '\x00\x83\x00\x04\x06\x68\x69\x00' hi 0
check raw-text status '\x00\x83\x00\x08\x06\x61\x62\x0a\x5c\xff\x0a\x00' $'ab\n\\\xff\n' 0
binary=
for ((byte=0; byte<256; byte++)); do
  printf -v escaped '\\x%02x' "$byte"
  binary+=$escaped
done
printf '%b' "$binary" >"$work/binary"
EXPECTED_FILE="$work/binary" check all-byte-values status "\x00\x83\x01\x02\x06${binary}\x00" '' 0
check trailing-newline status '\x00\x83\x00\x05\x06\x61\x62\x0a\x00' $'ab\n' 0
check empty-text who '\x00\x83\x00\x02\x06\x00' '' 0
check null playing '\x00\x83\x00\x01\x00' '' 2
check float ping '\x00\x83\x00\x05\x2a\x00\x00\x80\x3f' 1 0
check float-zero ping '\x00\x83\x00\x05\x2a\x00\x00\x00\x00' 0 0
check float-fraction ping '\x00\x83\x00\x05\x2a\x00\x00\x20\xc0' -2.5 0
check signature ping '\xff\xff\x00\x05\x2a\x00\x00\x80\x3f' '' 1
check truncated-body who '\x00\x83\x00\x0a\x06\x61\x62\x63\x64' '' 1
check truncated-header ping '\x00\x83\x00' '' 1
check missing-terminator who '\x00\x83\x00\x03\x06\x61\x62' '' 1
check missing-text-payload who '\x00\x83\x00\x01\x06' '' 1
check unknown-type ping '\x00\x83\x00\x01\x07' '' 1
check invalid-null ping '\x00\x83\x00\x02\x00\x00' '' 1
check invalid-float ping '\x00\x83\x00\x02\x2a\x00' '' 1
check empty-body ping '\x00\x83\x00\x00' '' 1
check literal-backslash 'status&review=hello\nworld\cend' '\x00\x83\x00\x01\x00' '' 2
check leading-question '?status' '\x00\x83\x00\x01\x00' '' 2
check double-question '??status' '\x00\x83\x00\x01\x00' '' 2
check literal-wildcards '*?[a-z]' '\x00\x83\x00\x01\x00' '' 2
check unicode 'café' '\x00\x83\x00\x01\x00' '' 2
check shell-injection "ping'; printf MARKER; #" '\x00\x83\x00\x05\x2a\x00\x00\x80\x3f' 1 0
check shell-expansion 'status$(printf MARKER)`printf MARKER`' '\x00\x83\x00\x01\x00' '' 2
printf -v padding '%280s' ''
padding=${padding// /x}
check long-request "protocol_reference=$padding" '\x00\x83\x00\x01\x00' '' 2
check long-response status "\x00\x83\x01\x1a\x06${padding}\x00" "$padding" 0
printf -v padding '%65528s' ''
padding=${padding// /x}
check max-response status "\x00\x83\xff\xff\x06${padding}xxxxx\x00" "${padding}xxxxx" 0
export BLOCK_OUTPUT=1
check blocked-output status "\x00\x83\xff\xff\x06${padding}xxxxx\x00" '' 124
unset BLOCK_OUTPUT
check max-frame "$padding" '\x00\x83\x00\x01\x00' '' 2
if "$CLIENT_SHELL" "$CLIENT_SCRIPT" 127.0.0.1 1 "${padding}x" >"$work/out" 2>"$work/err"; then
  printf 'FAIL oversized query accepted\n'
  ((failures+=1))
elif [[ -s $work/out ]] || ! grep -q 'two-byte frame length' "$work/err"; then
  printf 'FAIL oversized query not rejected before connection\n'
  ((failures+=1))
else
  printf 'PASS oversized query\n'
fi
export STALL=1
check timeout ping '' '' 124
unset STALL

export HOLD_OPEN=1
check persistent-connection status '\x00\x83\x00\x04\x06\x68\x69\x00' hi 0
unset HOLD_OPEN

export FRAGMENT=1
check fragmented-response status '\x00\x83\x00\x04\x06\x68\x69\x00' hi 0
printf '%s failures\n' "$failures"
((failures == 0))
