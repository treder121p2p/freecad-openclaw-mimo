with open('/opt/freecad/bridge/ai_bridge.py','r') as f:
    c = f.read()

old = 'FreeCADGui.ActiveDocument.ActiveView.saveImage(path, 800, 600, "PNG")'
new = 'ad = FreeCADGui.ActiveDocument\nif ad and ad.ActiveView:\n    ad.ActiveView.saveImage(path, 800, 600, "PNG")\nelse:\n    raise RuntimeError("No active document/view for screenshot")'

c = c.replace(old, new)

with open('/opt/freecad/bridge/ai_bridge.py','w') as f:
    f.write(c)

print('Patched OK')
