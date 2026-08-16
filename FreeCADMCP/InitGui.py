import sys as _sys
import os as _os
import traceback as _tb

_LOG = "/var/log/freecad/mcp_addon.log"

def _alog(msg):
    try:
        with open(_LOG, "a") as _f:
            _f.write(msg + "\n")
    except Exception:
        pass

try:
    _addon_dir = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    import inspect as _inspect
    _addon_dir = _os.path.dirname(_os.path.abspath(_inspect.getfile(_inspect.currentframe())))
if _addon_dir not in _sys.path:
    _sys.path.insert(0, _addon_dir)

_alog("InitGui.py loaded, addon_dir=" + _addon_dir)

try:
    class FreeCADMCPAddonWorkbench(Workbench):
        MenuText = "MCP Addon"
        ToolTip = "Addon for MCP Communication"

        def Initialize(self):
            _alog("Workbench.Initialize called")
            try:
                from rpc_server import rpc_server
                _alog("rpc_server imported OK")
            except Exception as e:
                _alog("rpc_server import FAILED: " + str(e))
                _alog(_tb.format_exc())
                return

            commands = [
                "Start_RPC_Server",
                "Stop_RPC_Server",
                "Toggle_Auto_Start",
                "Toggle_Remote_Connections",
                "Configure_Allowed_IPs",
            ]
            self.appendToolbar("FreeCAD MCP", commands)
            self.appendMenu("FreeCAD MCP", commands)
            _alog("Toolbar and menu added")

        def Activated(self):
            _alog("Workbench activated")

        def Deactivated(self):
            pass

        def ContextMenu(self, recipient):
            pass

        def GetClassName(self):
            return "Gui::PythonWorkbench"

    Gui.addWorkbench(FreeCADMCPAddonWorkbench())
    _alog("Workbench registered OK")
except Exception as e:
    _alog("Workbench registration FAILED: " + str(e))
    _alog(_tb.format_exc())


def _auto_start_mcp():
    # _alog must be local — FreeCAD's InitGui execution context may not expose module globals
    def _alog(msg):
        try:
            with open(_LOG, "a") as _f:
                _f.write(msg + "\n")
        except Exception:
            pass

    _alog("_auto_start_mcp called")
    try:
        from rpc_server import rpc_server
        _alog("rpc_server imported for auto-start")

        settings = rpc_server.load_settings()
        _alog("Settings: " + str(settings))
        if not settings.get("auto_start_rpc", False):
            _alog("auto_start_rpc is false, skipping")
            return

        msg = rpc_server.start_rpc_server()
        _alog("RPC start result: " + msg)
        FreeCAD.Console.PrintMessage(f"[MCP] Auto-start: {msg}\n")
    except Exception as e:
        _alog("Auto-start FAILED: " + str(e))
        _alog(_tb.format_exc())
        FreeCAD.Console.PrintWarning(f"[MCP] Auto-start failed: {e}\n")


from PySide import QtCore

_alog("Scheduling _auto_start_mcp via QTimer")
QtCore.QTimer.singleShot(0, _auto_start_mcp)
