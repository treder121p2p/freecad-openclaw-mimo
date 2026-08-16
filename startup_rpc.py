"""Startup script for FreeCAD MCP RPC server.
Run inside FreeCAD: freecadcmd startup_rpc.py

Strategy:
  1. Check if RPC is already running (auto-started by InitGui.py)
  2. If yes → exit cleanly (no duplicate)
  3. If no → try to start with retry (3 attempts, 2s delay)
"""
import sys
import os
import time
import traceback
import http.client

log_file = "/var/log/freecad/rpc_startup.log"

def log(msg):
    try:
        with open(log_file, "a") as f:
            f.write(msg + "\n")
    except:
        pass

def rpc_ping(host="localhost", port=9875, timeout=3):
    """Check if RPC server is already responding."""
    try:
        c = http.client.HTTPConnection(host, port, timeout=timeout)
        body = '<?xml version="1.0"?><methodCall><methodName>ping</methodName><params></params></methodCall>'
        c.request("POST", "/", body.encode(), {"Content-Type": "text/xml"})
        resp = c.getresponse().read().decode()
        return "<boolean>1</boolean>" in resp
    except Exception:
        return False

log("=== RPC startup script started ===")

# Step 1: Check if RPC is already running
if rpc_ping():
    log("RPC already running on :9875 (auto-started by InitGui.py) — exiting")
    print("[MCP] RPC already running, no action needed")
    sys.exit(0)

# Step 2: Try to start RPC with retry
try:
    try:
        addon_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        addon_dir = "/config/Mod/FreeCADMCP"

    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)

    log("Addon dir: " + addon_dir)

    from rpc_server import rpc_server
    log("rpc_server module imported")

    settings = rpc_server.load_settings()
    log("Settings loaded: " + str(settings))

    if not settings.get("auto_start_rpc", False):
        log("auto_start_rpc is false, skipping")
        print("[MCP] auto_start_rpc is false")
        sys.exit(0)

    # Retry up to 3 times
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        log(f"RPC start attempt {attempt}/{max_attempts}")
        try:
            msg = rpc_server.start_rpc_server()
            log("RPC start result: " + msg)
            print(f"[MCP] Startup: {msg}")
            break
        except OSError as e:
            if "Address already in use" in str(e):
                log(f"Port 9875 busy on attempt {attempt}")
                # Re-check: maybe it started between attempts
                if rpc_ping():
                    log("RPC came up during retry — exiting")
                    print("[MCP] RPC appeared during retry")
                    break
                if attempt < max_attempts:
                    log(f"Retrying in 2s...")
                    time.sleep(2)
                else:
                    log("All attempts exhausted — port 9875 permanently busy")
                    print("[MCP] Port 9875 busy after all retries")
            else:
                raise

except Exception as e:
    log("ERROR: " + str(e))
    log(traceback.format_exc())
    print("[MCP] Startup error: " + str(e))
