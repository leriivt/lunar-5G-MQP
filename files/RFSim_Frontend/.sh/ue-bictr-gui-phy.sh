#!/usr/bin/env bash
# PHY-test UE over a real USRP. Optional $1 = USRP args (default addr=10.10.10.13).
USRP_ADDR="${1:-addr=10.10.10.13}"
cd /home/lunar5g/openairinterface5g/cmake_targets/ran_build/build || exit 1
pgrep -x nr-softmodem >/dev/null || { echo "WARNING: no nr-softmodem running. Start the gNB first."; sleep 3; }
[ -f reconfig.raw ] && [ -f rbconfig.raw ] || echo "WARNING: reconfig.raw/rbconfig.raw missing — gNB may not have finished starting."
echo "Starting UE on USRP ($USRP_ADDR) over BICTR_LUNAR terrain channel (phy-test, noS1)."
echo
sudo ./nr-uesoftmodem --phy-test -r 106 --numerology 1 --band 78 -C 3319680000 -E --ssb 516 --usrp-args "$USRP_ADDR" --ue-txgain 30 --ue-rxgain 90
echo; echo "----- process exited (code $?) -----"; read -rp "Press Enter to close this window..." _