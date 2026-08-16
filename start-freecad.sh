#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=${DISPLAY:-:1}
export VNC_PORT=${VNC_PORT:-5900}
export NOVNC_PORT=${NOVNC_PORT:-6080}
export HOME=${HOME:-/config}

mkdir -p "$HOME" /var/log/freecad

# Clean stale X lock/socket
if [ "$DISPLAY" = ":1" ]; then
  rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
fi

# Kill any stale processes
pkill -f "Xvfb $DISPLAY" 2>/dev/null || true
pkill -f "x11vnc -display $DISPLAY" 2>/dev/null || true
pkill -f "websockify --web=/usr/share/novnc/" 2>/dev/null || true
pkill -f fluxbox 2>/dev/null || true

# X virtual display
Xvfb "$DISPLAY" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset > /var/log/freecad/xvfb.log 2>&1 &

# Lightweight window manager
fluxbox > /var/log/freecad/fluxbox.log 2>&1 &

# VNC server
x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport "$VNC_PORT" > /var/log/freecad/x11vnc.log 2>&1 &

# noVNC websocket proxy
websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" > /var/log/freecad/novnc.log 2>&1 &

# Wait for X to be ready
sleep 2

# Find FreeCAD AppImage
FREECAD_BIN=""
if [ -x /opt/freecad/FreeCAD.AppImage ]; then
  FREECAD_BIN="/opt/freecad/FreeCAD.AppImage"
  EXTRA_ARGS="--appimage-extract-and-run"
elif command -v freecad >/dev/null 2>&1; then
  FREECAD_BIN="freecad"
  EXTRA_ARGS=""
elif command -v FreeCAD >/dev/null 2>&1; then
  FREECAD_BIN="FreeCAD"
  EXTRA_ARGS=""
else
  echo "FreeCAD binary not found" >&2
  exit 1
fi

echo "FreeCAD container started"
echo "- VNC:    0.0.0.0:${VNC_PORT}"
echo "- noVNC:  http://0.0.0.0:${NOVNC_PORT}/vnc.html"
echo "- RPC:    0.0.0.0:9875"

# Start FreeCAD with GUI (background)
HOME="$HOME" $FREECAD_BIN $EXTRA_ARGS > /var/log/freecad/freecad.log 2>&1 &
FREECAD_PID=$!

echo "FreeCAD started with PID: $FREECAD_PID" >> /var/log/freecad/rpc_startup.log

# Background: wait for FreeCAD config dir (sign of full init), then start RPC
(
  echo "Waiting for FreeCAD to initialize..." >> /var/log/freecad/rpc_startup.log

  for i in $(seq 1 120); do
    if ! kill -0 "$FREECAD_PID" 2>/dev/null; then
      echo "FreeCAD exited prematurely at iteration $i" >> /var/log/freecad/rpc_startup.log
      exit 1
    fi
    # FreeCAD creates .config/FreeCAD/ when GUI is ready
    if [ -d "$HOME/.config/FreeCAD" ] && [ $i -gt 10 ]; then
      echo "FreeCAD config dir found at iteration $i" >> /var/log/freecad/rpc_startup.log
      sleep 5
      break
    fi
    sleep 2
  done

  echo "Starting RPC server via freecadcmd..." >> /var/log/freecad/rpc_startup.log

  # Use freecadcmd (headless) to run the RPC startup script
  # --console runs in console mode, the script starts XML-RPC server
  HOME="$HOME" $FREECAD_BIN $EXTRA_ARGS --console /opt/freecad/startup_rpc.py \
    >> /var/log/freecad/rpc_startup.log 2>&1 &

  echo "RPC process launched" >> /var/log/freecad/rpc_startup.log
) &

# Keep container alive — start web UI server
node /opt/freecad/webui/server.js >> /var/log/freecad/webui.log 2>&1 &
echo "Web UI started on port 9876" >> /var/log/freecad/rpc_startup.log

# Start AI Bridge (MiMo ↔ FreeCAD RPC)
python3 /opt/freecad/bridge/ai_bridge.py >> /var/log/freecad/bridge.log 2>&1 &
echo "AI Bridge started on port 9877" >> /var/log/freecad/rpc_startup.log

# Watchdog: restart x11vnc if it dies
(
  while true; do
    sleep 10
    if ! pgrep -f "x11vnc -display" > /dev/null 2>&1; then
      echo "x11vnc died, restarting..." >> /var/log/freecad/rpc_startup.log
      x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport "$VNC_PORT" >> /var/log/freecad/x11vnc.log 2>&1 &
    fi
    if ! pgrep -f "websockify" > /dev/null 2>&1; then
      echo "websockify died, restarting..." >> /var/log/freecad/rpc_startup.log
      websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" >> /var/log/freecad/novnc.log 2>&1 &
    fi
  done
) &

# Watchdog: restart x11vnc if it dies
(
  while true; do
    sleep 10
    if ! pgrep -f "x11vnc -display" > /dev/null 2>&1; then
      echo "x11vnc died, restarting..." >> /var/log/freecad/rpc_startup.log
      x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport "$VNC_PORT" >> /var/log/freecad/x11vnc.log 2>&1 &
    fi
    if ! pgrep -f "websockify" > /dev/null 2>&1; then
      echo "websockify died, restarting..." >> /var/log/freecad/rpc_startup.log
      websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" >> /var/log/freecad/novnc.log 2>&1 &
    fi
  done
) &

# Watchdog: restart x11vnc if it dies
(
  while true; do
    sleep 10
    if ! pgrep -f "x11vnc -display" > /dev/null 2>&1; then
      echo "x11vnc died, restarting..." >> /var/log/freecad/rpc_startup.log
      x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport "$VNC_PORT" >> /var/log/freecad/x11vnc.log 2>&1 &
    fi
    if ! pgrep -f "websockify" > /dev/null 2>&1; then
      echo "websockify died, restarting..." >> /var/log/freecad/rpc_startup.log
      websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" >> /var/log/freecad/novnc.log 2>&1 &
    fi
  done
) &

# Watchdog: restart x11vnc if it dies
(
  while true; do
    sleep 10
    if ! pgrep -f "x11vnc -display" > /dev/null 2>&1; then
      echo "x11vnc died, restarting..." >> /var/log/freecad/rpc_startup.log
      x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport "$VNC_PORT" >> /var/log/freecad/x11vnc.log 2>&1 &
    fi
    if ! pgrep -f "websockify" > /dev/null 2>&1; then
      echo "websockify died, restarting..." >> /var/log/freecad/rpc_startup.log
      websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" >> /var/log/freecad/novnc.log 2>&1 &
    fi
  done
) &

# Watchdog: restart x11vnc if it dies
(
  while true; do
    sleep 10
    if ! pgrep -f "x11vnc -display" > /dev/null 2>&1; then
      echo "x11vnc died, restarting..." >> /var/log/freecad/rpc_startup.log
      x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport "$VNC_PORT" >> /var/log/freecad/x11vnc.log 2>&1 &
    fi
    if ! pgrep -f "websockify" > /dev/null 2>&1; then
      echo "websockify died, restarting..." >> /var/log/freecad/rpc_startup.log
      websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" >> /var/log/freecad/novnc.log 2>&1 &
    fi
  done
) &

tail -f /var/log/freecad/*.log
