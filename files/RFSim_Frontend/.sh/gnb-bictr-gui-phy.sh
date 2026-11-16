#!/usr/bin/env bash
IP="${1:-addr=10.10.10.11}"
DL_MCS="${2:-9}"
UL_MCS="${3:-9}"
[ -f "$IP" ] || { echo "Config not found: $IP"; exit 1 ; }
cd /home/lunar5g/openairinterface5g/cmake_targets/ran_build/build || exit 1
echo "Starting gNB over BICTR_LUNAR terrain channel (phy-test, noS1)."
echo "Start the UE launcher once 'reconfig.raw' / 'rbconfig.raw' appear here."
echo
sudo ./nr-softmodem -O "$IP" \
  --phy-test --noS1 --parallel-config PARALLEL_SINGLE_THREAD \
  --gNBs.[0].min_rxtxtime 6 -m "$DL_MCS" -t "$UL_MCS"
echo; echo "----- process exited (code $?) -----"; read -rp "Press Enter to close this window..." _