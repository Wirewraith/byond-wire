#!/bin/bash
# Shared wire captures; no BYOND runtime is needed to run these regressions.
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
unhex() {
  local hex=$1 i
  for ((i=0; i<${#hex}; i+=2)); do printf '%b' "\\x${hex:i:2}"; done
}
for variant in bash shell; do
  runner=bash
  [[ $variant == bash ]] || runner=sh
  printf '. "%s/%s/byond-wire.sh"\nbyond_decode_text\n' "$PWD" "$variant" >"$work/decode.sh"
  printf xy >"$work/input"
  "$runner" -c '. "$1"; IFS=:; byond_decode_text; status=$?; [ "$IFS" = : ] || exit 99; exit "$status"' ignored "$PWD/$variant/byond-wire.sh" <"$work/input" >"$work/output"
  cmp "$work/input" "$work/output"
  checks=0
  while IFS=$'\t' read -r name hex expected; do
    [[ $name != \#* ]] || continue
    unhex "$hex" >"$work/input"
    code=0
    "$runner" "$work/decode.sh" <"$work/input" >"$work/output" 2>"$work/error" || code=$?
    if [[ $expected == - ]]; then
      [[ $code == 1 && ! -s $work/output && -s $work/error ]] || { printf 'FAIL %s %s rejected incorrectly (exit %s)\n' "$variant" "$name" "$code"; exit 1; }
    else
      unhex "$expected" >"$work/expected"
      [[ $code == 0 ]] && cmp -s "$work/expected" "$work/output" || { printf 'FAIL %s %s (exit %s)\n' "$variant" "$name" "$code"; exit 1; }
    fi
    ((checks+=1))
  done <tests/text-vectors.tsv
  head -c 65533 /dev/zero | tr '\0' x >"$work/input"
  "$runner" "$work/decode.sh" <"$work/input" >"$work/output"
  cmp "$work/input" "$work/output"
  # Dense markers exercise batch removal; a late error must never leak a prefix.
  printf -v marked '%32766s' ''
  marked=${marked// /$'\xff\x15'}
  printf '%s' "$marked" >"$work/input"
  "$runner" "$work/decode.sh" <"$work/input" >"$work/output"
  [[ ! -s $work/output ]]
  head -c 65532 /dev/zero | tr '\0' x >"$work/input"
  printf '\xff' >>"$work/input"
  code=0
  "$runner" "$work/decode.sh" <"$work/input" >"$work/output" 2>"$work/error" || code=$?
  [[ $code == 1 && ! -s $work/output && -s $work/error ]]
  printf '%s: %s text vectors and large input passed\n' "$variant" "$checks"
done
