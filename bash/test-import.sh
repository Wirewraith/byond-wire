#!/bin/bash
set -eu
cd "$(dirname "$0")"
if [[ $# == 0 ]]; then set -- bash shell; fi
for variant; do
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  library=$(cd "../$variant" && pwd)/byond-wire.sh
  runner=bash
  [[ $variant == bash ]] || runner=sh
  "$runner" -e -c '. "$1"; printf alive' ignored "$library" >"$work/out"
  [[ $(cat "$work/out") == alive ]]
  printf '. "%s"\n' "$library" >"$work/client.sh"
  cat >>"$work/client.sh" <<'EOF'
q=caller work=caller
flags=$-
mask=$(umask)
trap 'exit 99' ALRM
saved_traps=$(trap)
die() { return 99; }
exec 3<"$0"
# Repeat an invalid call in the same shell; it must return without exiting.
for attempt in 1 2; do
  if byond_topic >/dev/null 2>&1; then exit 98; else [ "$?" -eq 1 ] || exit 98; fi
done
sleep 30 & unrelated=$!
byond_topic "$@"
status=$?
kill -0 "$unrelated" || exit 98
kill "$unrelated"
wait "$unrelated" 2>/dev/null || :
[ "$q:$work:$-:$(umask):$(trap)" = "caller:caller:$flags:$mask:$saved_traps" ] || exit 98
die
[ "$?" -eq 99 ] || exit 98
IFS= read -r first <&3 || exit 98
exit "$status"
EOF
  CLIENT_SHELL=$runner CLIENT_SCRIPT="$work/client.sh" bash test-cli.sh
  rm -rf "$work"
  trap - EXIT
done
