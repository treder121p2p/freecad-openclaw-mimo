#!/usr/bin/env bash
set -uo pipefail

export DISPLAY=${DISPLAY:-:1}
export VNC_PORT=${VNC_PORT:-5900}
export NOVNC_PORT=${NOVNC_PORT:-6080}
export HOME=${HOME:-/config}

mkdir -p "$HOME" /var/log/freecad

# --- Phase 1: Kill stale processes (wait for them to die) ---
if [ "$DISPLAY" = ":1" ]; then
  rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
fi

pkill -f "Xvfb $DISPLAY" 2>/dev/null
pkill -f "x11vnc -display $DISPLAY" 2>/dev/null
pkill -f "websockify --web=/usr/share/novnc/" 2>/dev/null
pkill -f fluxbox 2>/dev/null
pkill -f "ai_bridge.py" 2>/dev/null
pkill -f "node.*server.js" 2>/dev/null
sleep 2

# --- Phase 2: Start X environment ---
Xvfb "$DISPLAY" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset > /var/log/freecad/xvfb.log 2>&1 &
fluxbox > /var/log/freecad/fluxbox.log 2>&1 &

# VNC with auto-restart (localhost only — external access via WebUI proxy)
(
  while true; do
    x11vnc -display "$DISPLAY" -forever -shared -listen 127.0.0.1 -rfbport "$VNC_PORT" \
      -rfbauth /opt/freecad/.vnc_pass >> /var/log/freecad/x11vnc.log 2>&1
    sleep 3
  done
) &

# noVNC websocket proxy with auto-restart
(
  while true; do
    websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:"$VNC_PORT" >> /var/log/freecad/novnc.log 2>&1
    sleep 3
  done
) &

sleep 2

# --- Phase 3: Start FreeCAD GUI ---
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

HOME="$HOME" $FREECAD_BIN $EXTRA_ARGS > /var/log/freecad/freecad.log 2>&1 &
FREECAD_PID=$!
echo "FreeCAD started with PID: $FREECAD_PID" > /var/log/freecad/rpc_startup.log

# --- Phase 4: Wait for RPC (auto-started by InitGui.py) ---
echo "Waiting for RPC server on :9875..." >> /var/log/freecad/rpc_startup.log
RPC_READY=0
for i in $(seq 1 90); do
  if ! kill -0 "$FREECAD_PID" 2>/dev/null; then
    echo "FreeCAD exited prematurely at iteration $i" >> /var/log/freecad/rpc_startup.log
    break
  fi
  if python3 -c "
import http.client
c = http.client.HTTPConnection('localhost', 9875, timeout=2)
body = '<?xml version=\"1.0\"?><methodCall><methodName>ping</methodName><params></params></methodCall>'
c.request('POST', '/', body.encode(), {'Content-Type': 'text/xml'})
r = c.getresponse().read().decode()
exit(0 if '<boolean>1</boolean>' in r else 1)
" 2>/dev/null; then
    echo "RPC ready after ${i}x2 seconds (iteration $i)" >> /var/log/freecad/rpc_startup.log
    RPC_READY=1
    break
  fi
  sleep 2
done

if [ "$RPC_READY" -eq 0 ]; then
  echo "WARNING: RPC not ready after 180s — starting via freecadcmd fallback" >> /var/log/freecad/rpc_startup.log
  HOME="$HOME" $FREECAD_BIN $EXTRA_ARGS --console /opt/freecad/startup_rpc.py \
    >> /var/log/freecad/rpc_startup.log 2>&1 &
  echo "Fallback RPC process launched" >> /var/log/freecad/rpc_startup.log
fi

# --- Phase 5: Start Web UI ---
node /opt/freecad/webui/server.js >> /var/log/freecad/webui.log 2>&1 &
echo "Web UI started on port 9876" >> /var/log/freecad/rpc_startup.log

# --- Phase 6: Start AI Bridge (with auto-restart) ---
(
  while true; do
    python3 /opt/freecad/bridge/ai_bridge.py >> /var/log/freecad/bridge.log 2>&1
    sleep 5
  done
) &
echo "AI Bridge started on port 9877 (with restart loop)" >> /var/log/freecad/rpc_startup.log

# --- Keep container alive ---
tail -f /var/log/freecad/*.log
