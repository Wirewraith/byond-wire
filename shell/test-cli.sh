#!/bin/sh
# Reuse the wire-level suite; tests require Bash, socat and GNU coreutils.
cd "$(dirname "$0")" || exit 1
CLIENT_SHELL=${CLIENT_SHELL:-sh} CLIENT_SCRIPT="$PWD/cli.sh" \
  exec bash ../bash/test-cli.sh "$@"
