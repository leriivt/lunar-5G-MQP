#!/usr/bin/env bash
cd /home/lunar5g/openairinterface5g/cmake_targets/ran_build/build || exit 1
pgrep -x nr-softmodem >/dev/null || { echo "WARNING: no nr-softmodem running. Start the gNB first."; sleep 3; }
[ -f reconfig.raw ] && [ -f rbconfig.raw ] || echo "WARNING: reconfig.raw/rbconfig.raw missing — gNB may not have finished starting."
echo "Starting UE over BICTR_LUNAR terrain channel (phy-test, noS1)."
echo
sudo ./nr-uesoftmodem -O "$CONF" --rfsim --phy-test --noS1 --rrc_config_path .
echo; echo "----- process exited (code $?) -----"; read -rp "Press Enter to close this window..." _
