#!/bin/bash
set -e

# Start virtual framebuffer display on :99
Xvfb :99 -screen 0 1280x900x24 &
export DISPLAY=:99

# Give Xvfb a moment to start
sleep 1

# Start VNC server — password protected if VNC_PASSWORD is set
if [ -n "$VNC_PASSWORD" ]; then
    x11vnc -display :99 -forever -passwd "$VNC_PASSWORD" \
           -listen 0.0.0.0 -rfbport 5900 -noxdamage &
else
    x11vnc -display :99 -forever -nopw \
           -listen 0.0.0.0 -rfbport 5900 -noxdamage &
fi

# Start a minimal terminal in the VNC session so the desktop isn't empty
xterm &

# Unset DISPLAY so gunicorn/Selenium use headless Chrome without X conflicts
unset DISPLAY

# Start the Flask app
exec gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 30 app:app
