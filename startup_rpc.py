"""Startup script for FreeCAD MCP RPC server.
Run inside FreeCAD: freecadcmd startup_rpc.py
"""
import sys
import os
import traceback

log_file = "/var/log/freecad/rpc_startup.log"

def log(msg):
    try:
        with open(log_file, "a") as f:
            f.write(msg + "\n")
    except:
        pass

log("=== RPC startup script started ===")

try:
    # Determine addon directory — __file__ may not exist in all contexts
    try:
        addon_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        addon_dir = "/config/Mod/FreeCADMCP"

    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)

    log("Addon dir: " + addon_dir)
    log("sys.path[0]: " + sys.path[0])

    from rpc_server import rpc_server
    log("rpc_server module imported")

    settings = rpc_server.load_settings()
    log("Settings loaded: " + str(settings))

    if not settings.get("auto_start_rpc", False):
        log("auto_start_rpc is false, skipping")
    else:
        msg = rpc_server.start_rpc_server()
        log("RPC start result: " + msg)
        print("[MCP] Startup: " + msg)

except Exception as e:
    log("ERROR: " + str(e))
    log(traceback.format_exc())
    print("[MCP] Startup error: " + str(e))
