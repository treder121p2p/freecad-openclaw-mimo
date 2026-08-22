import re

with open('/opt/freecad/bridge/freecad_api.py', 'r') as f:
    content = f.read()

# Add _safe_doc method after __init__
old_init_end = "        self._objects = []"
new_init_end = """        self._objects = []

    def _safe_doc(self):
        try:
            if self.doc is None or not self.doc.Name:
                raise ValueError('doc is None')
            _ = self.doc.Objects
            return self.doc
        except:
            import FreeCAD
            self.doc = FreeCAD.activeDocument() or FreeCAD.newDocument('AIDoc')
            return self.doc"""

content = content.replace(old_init_end, new_init_end, 1)

# Replace self.doc with self._safe_doc() for all method calls
content = content.replace('self.doc.addObject', 'self._safe_doc().addObject')
content = content.replace('self.doc.recompute()', 'self._safe_doc().recompute()')
content = content.replace('self.doc.removeObject', 'self._safe_doc().removeObject')

# Fix export methods
content = content.replace('for o in self.doc.Objects', 'for o in self._safe_doc().Objects')
content = content.replace('if doc and doc.Objects', 'if self._safe_doc() and self._safe_doc().Objects')

with open('/opt/freecad/bridge/freecad_api.py', 'w') as f:
    f.write(content)

print('Patched OK')
