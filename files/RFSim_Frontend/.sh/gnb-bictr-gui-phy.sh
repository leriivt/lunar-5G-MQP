#!/usr/bin/env bash
cd /home/lunar5g/openairinterface5g/cmake_targets/ran_build/build || exit 1
echo "Starting gNB over BICTR_LUNAR terrain channel (phy-test, noS1)."
echo "Start the UE launcher once 'reconfig.raw' / 'rbconfig.raw' appear here."
echo
sudo ./nr-softmodem -O /home/lunar5g/openairinterface5g/targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb1.sa.band78.fr1.106PRB.prs.usrpx310.conf \
  --phy-test --noS1 --parallel-config PARALLEL_SINGLE_THREAD \
  --gNBs.[0].min_rxtxtime 6 -m 9 -t 9
echo; echo "----- process exited (code $?) -----"; read -rp "Press Enter to close this window..." _