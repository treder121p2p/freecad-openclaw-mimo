import xmlrpc.client
p = xmlrpc.client.ServerProxy('http://localhost:9875')
r = p.execute_code('import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Test"); box = doc.addObject("Part::Box", "Box"); doc.recompute(); print("Created Box")')
print(type(r))
print(r)
