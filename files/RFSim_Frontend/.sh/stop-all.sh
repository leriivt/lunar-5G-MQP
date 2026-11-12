#!/usr/bin/env bash
echo "Stopping nr-softmodem / nr-uesoftmodem..."
sudo pkill -TERM -x nr-softmodem; sudo pkill -TERM -x nr-uesoftmodem
sleep 2
sudo pkill -KILL -x nr-softmodem 2>/dev/null; sudo pkill -KILL -x nr-uesoftmodem 2>/dev/null
pgrep -a -x nr-softmodem; pgrep -a -x nr-uesoftmodem
echo "Done."; sleep 2
