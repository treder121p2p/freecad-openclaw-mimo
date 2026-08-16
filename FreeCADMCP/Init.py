# FreeCADMCP Init.py — non-GUI initialization
# FreeCAD scans Mod/*/Init.py on startup regardless of GUI mode
import sys
import os
import traceback

# __file__ may not be defined in FreeCAD's execution context
try:
    _addon_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import inspect
    _addon_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

_LOG = "/var/log/freecad/mcp_init.log"

def _alog(msg):
    try:
        with open(_LOG, "a") as f:
            f.write(msg + "\n")
    except:
        pass

_alog("Init.py loaded from: " + _addon_dir)

try:
    from rpc_server import settings as rpc_settings
    _alog("rpc_server.settings imported OK")
except Exception as e:
    _alog("rpc_server.settings import FAILED: " + str(e))
    _alog(traceback.format_exc())
