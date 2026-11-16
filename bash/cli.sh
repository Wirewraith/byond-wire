#!/bin/bash
case $0 in
  */*) . "${0%/*}/byond-wire.sh" ;;
  *) . ./byond-wire.sh ;;
esac
byond_topic "$@"
