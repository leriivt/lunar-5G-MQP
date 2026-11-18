#!/usr/bin/env bash
# PHY-test gNB over a real USRP. $1 = gNB .conf, $2/$3 = DL/UL MCS (default 9).
CONF="${1:?Error: missing config file argument}"
DL_MCS="${2:-9}"
UL_MCS="${3:-9}"
[ -f "$CONF" ] || { echo "Config not found: $CONF"; exit 1 ; }
cd /home/lunar5g/openairinterface5g/cmake_targets/ran_build/build || exit 1
echo "Starting gNB on USRP with $CONF (phy-test, noS1, DL MCS $DL_MCS, UL MCS $UL_MCS)."
echo
sudo ./nr-softmodem -O "$CONF" \
  --phy-test --noS1 --parallel-config PARALLEL_SINGLE_THREAD \
  --gNBs.[0].min_rxtxtime 6 -m "$DL_MCS" -t "$UL_MCS"
echo; echo "----- process exited (code $?) -----"; read -rp "Press Enter to close this window..." _
