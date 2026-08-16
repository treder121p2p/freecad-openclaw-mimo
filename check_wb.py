import FreeCAD
import FreeCADGui
import sys

print("UserAppDataDir:", FreeCAD.getUserAppDataDir())
print("Macro dir:", FreeCAD.getUserMacroDir())

wb = FreeCADGui.listWorkbenches()
print("Workbenches:", list(wb.keys()))
print("Total:", len(wb))

# Check if MCP addon workbench is registered
for k in wb:
    if "MCP" in k or "FreeCAD" in k.lower():
        print("Found:", k, "->", wb[k])

sys.exit(0)
