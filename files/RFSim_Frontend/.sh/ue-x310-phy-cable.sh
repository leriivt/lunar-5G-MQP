#!/usr/bin/env bash
# UE on this machine's X310, cabled over SMA to a phy-test gNB on another computer.
# ALWAYS put >= 30 dB of attenuation between the two radios' SMA ports.
#
# Everything below must match the gNB machine's command/config.

BUILD=~/openairinterface5g/cmake_targets/ran_build/build
USRP_ADDR="10.10.10.11"        # this machine's X310
FREQ=3319680000                # must match the gNB's carrier (-C / absoluteFrequencySSB)
PRB=106; NUMEROLOGY=1; BAND=78 # must match the gNB config
THREE_QUARTER=""               # set to "-E" ONLY if the gNB runs with -E
RX_GAIN=90; TX_GAIN=0          # start low over a cable; raise RX_GAIN if no sync

# Where the gNB wrote reconfig.raw / rbconfig.raw (on the gNB machine).
# Leave GNB_HOST empty to use files already copied into RRC_DIR.
GNB_HOST=""                    # e.g. user@192.168.1.50
GNB_BUILD="~/openairinterface5g/cmake_targets/ran_build/build"
RRC_DIR="$BUILD/gnb-rrc"

mkdir -p "$RRC_DIR" || exit 1
if [ -n "$GNB_HOST" ]; then
  echo "Copying reconfig.raw / rbconfig.raw from $GNB_HOST ..."
  scp "$GNB_HOST:$GNB_BUILD/reconfig.raw" "$GNB_HOST:$GNB_BUILD/rbconfig.raw" "$RRC_DIR/" || {
    echo "Copy failed. Is the gNB running and has it written the files?"
    read -rp "Press Enter to close this window..." _; exit 1; }
fi
[ -f "$RRC_DIR/reconfig.raw" ] && [ -f "$RRC_DIR/rbconfig.raw" ] || {
  echo "Missing $RRC_DIR/reconfig.raw or rbconfig.raw — copy them from the running gNB first."
  read -rp "Press Enter to close this window..." _; exit 1; }

cd "$BUILD" || exit 1
echo "Starting UE on X310 $USRP_ADDR at $FREQ Hz (phy-test, noS1, cabled)."
echo
sudo ./nr-uesoftmodem --phy-test --noS1 --rrc_config_path "$RRC_DIR" \
  --usrp-args "addr=$USRP_ADDR" \
  -r "$PRB" --numerology "$NUMEROLOGY" --band "$BAND" -C "$FREQ" $THREE_QUARTER \
  --ue-fo-compensation --ue-rxgain "$RX_GAIN" --ue-txgain "$TX_GAIN"
rc=$?; echo; echo "----- process exited (code $rc) -----"; read -rp "Press Enter to close this window..." _
