#!/bin/sh
# A virtual screen and a virtual speaker for the browser, then the bot.
set -e
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit
sleep 1
exec node src/index.js
