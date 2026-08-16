import sys, os
# Check if addon was discovered
mod_dir = os.path.join("/config/Mod", "FreeCADMCP")
sys.path.insert(0, mod_dir)
try:
    from rpc_server import rpc_server
    settings = rpc_server.load_settings()
    print("Settings:", settings)
    msg = rpc_server.start_rpc_server()
    print("RPC start:", msg)
except Exception as e:
    print("ERROR:", e)
    import traceback
    traceback.print_exc()
