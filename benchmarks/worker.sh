# Benchmark-only dependencies: GNU date, mktemp, wc, awk; existing library utilities.
. "$1"
host=$2 port=$3
work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT
while IFS="$(printf '\t')" read -r mode query kind; do
    start=$(date +%s%N)
    code=0
    byond_topic "$host" "$port" "$query" >"$work/raw" 2>"$work/error" || code=$?
    output=$work/raw
    if [ "$code" = 0 ] && [ "$kind" = text ] && [ "$mode" = decoded ]; then
        output=$work/text
        byond_decode_text <"$work/raw" >"$work/text" 2>"$work/error" || code=$?
    fi
    end=$(date +%s%N)
    ms=$(awk "BEGIN {print ($end - $start) / 1000000}")
    if [ "$code" = 2 ]; then
        printf '%s\tnull\t0\n' "$ms"
    elif [ "$code" != 0 ]; then
        printf '%s\terror\texit %s: ' "$ms" "$code"
        tr '\r\n' '  ' <"$work/error"
        printf '\n'
    elif [ "$kind" = number ]; then
        if LC_ALL=C grep -Eq '^-?[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?$' "$output"; then
            printf '%s\tnumber\t4\n' "$ms"
        else
            printf '%s\terror\tinvalid number\n' "$ms"
        fi
    else
        printf '%s\ttext\t%s\n' "$ms" "$(wc -c <"$output")"
    fi
done
