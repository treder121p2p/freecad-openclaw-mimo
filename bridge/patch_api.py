#!/usr/bin/env python3
"""Fix freecad_api.py: through-hole, remove_old, through_hole helper"""
import re

with open('/opt/freecad/bridge/freecad_api.py', 'r') as f:
    c = f.read()

# 1. Fix cut() - add extend logic for through-holes + remove_old
old_cut = '''    def cut(self, base, tool, name=None):
        """\u0412\u044b\u0447\u0438\u0442\u0430\u043d\u0438\u0435 (Boolean Cut)."""
        result = base.Shape.cut(tool.Shape)
        feat = self._safe_doc().addObject("Part::Feature", name or f"Cut_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        return self._add(feat)'''

new_cut = '''    def cut(self, base, tool, name=None, remove_old=False):
        """\u0412\u044b\u0447\u0438\u0442\u0430\u043d\u0438\u0435 (Boolean Cut). Extends tool for through-cuts."""
        try:
            tool_bb = tool.Shape.BoundBox
            base_bb = base.Shape.BoundBox
            ext = 0.5
            tool_copy = tool.Shape.copy()
            tool_copy.translate(FreeCAD.Vector(0, 0, base_bb.ZMin - tool_bb.ZMin - ext))
            sz = max(tool_bb.ZLength, 0.01)
            tool_copy.scale(1, 1, (base_bb.ZLength + 2*ext) / sz)
            result = base.Shape.cut(tool_copy)
        except:
            result = base.Shape.cut(tool.Shape)
        feat = self._safe_doc().addObject("Part::Feature", name or f"Cut_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        if remove_old:
            try: self._safe_doc().removeObject(base.Name)
            except: pass
            try: self._safe_doc().removeObject(tool.Name)
            except: pass
        return self._add(feat)'''

if old_cut in c:
    c = c.replace(old_cut, new_cut)
    print("Fixed cut()")
else:
    print("WARN: cut() pattern not found")

# 2. Fix fuse() - add remove_old
old_fuse = '''    def fuse(self, obj1, obj2, name=None):
        """\u041e\u0431\u044a\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 (Boolean Union)."""
        result = obj1.Shape.fuse(obj2.Shape)
        feat = self._safe_doc().addObject("Part::Feature", name or f"Fuse_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        return self._add(feat)'''

new_fuse = '''    def fuse(self, obj1, obj2, name=None, remove_old=False):
        """\u041e\u0431\u044a\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 (Boolean Union)."""
        result = obj1.Shape.fuse(obj2.Shape)
        feat = self._safe_doc().addObject("Part::Feature", name or f"Fuse_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        if remove_old:
            try: self._safe_doc().removeObject(obj1.Name)
            except: pass
            try: self._safe_doc().removeObject(obj2.Name)
            except: pass
        return self._add(feat)'''

if old_fuse in c:
    c = c.replace(old_fuse, new_fuse)
    print("Fixed fuse()")
else:
    print("WARN: fuse() pattern not found")

# 3. Add through_hole helper before intersect
old_intersect = '    def intersect(self, obj1, obj2, name=None):'

new_helpers = '''    def through_hole(self, base, cx, cy, radius, name=None):
        """\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u0441\u043a\u0432\u043e\u0437\u043d\u043e\u0435 \u043e\u0442\u0432\u0435\u0440\u0441\u0442\u0438\u0435 \u043f\u043e \u0446\u0435\u043d\u0442\u0440\u0443 (cx, cy)."""
        base_bb = base.Shape.BoundBox
        height = base_bb.ZLength + 2.0
        hole = self.cylinder(radius, height, name=(name or "Hole") + "_cyl")
        self.move(hole, x=cx, y=cy, z=base_bb.ZMin - 1.0)
        return self.cut(base, hole, name=name or f"Hole_{len(self._objects)}")

    def intersect(self, obj1, obj2, name=None):'''

if old_intersect in c:
    c = c.replace(old_intersect, new_helpers)
    print("Added through_hole()")
else:
    print("WARN: intersect() pattern not found")

# 4. Also extend intersect for consistency
old_intersect_body = '''    def intersect(self, obj1, obj2, name=None):
        """\u041f\u0435\u0440\u0435\u0441\u0435\u0447\u0435\u043d\u0438\u0435 (Boolean Common)."""
        result = obj1.Shape.common(obj2.Shape)'''

new_intersect_body = '''    def intersect(self, obj1, obj2, name=None, remove_old=False):
        """\u041f\u0435\u0440\u0435\u0441\u0435\u0447\u0435\u043d\u0438\u0435 (Boolean Common)."""
        result = obj1.Shape.common(obj2.Shape)'''

if old_intersect_body in c:
    c = c.replace(old_intersect_body, new_intersect_body)
    # Also add remove_old handling at end of intersect
    old_intersect_end = '''        self._objects.append(feat)
        return self._add(feat)

    def fillet'''
    new_intersect_end = '''        self._objects.append(feat)
        if remove_old:
            try: self._safe_doc().removeObject(obj1.Name)
            except: pass
            try: self._safe_doc().removeObject(obj2.Name)
            except: pass
        return self._add(feat)

    def fillet'''
    c = c.replace(old_intersect_end, new_intersect_end)
    print("Fixed intersect()")
else:
    print("WARN: intersect body pattern not found")

with open('/opt/freecad/bridge/freecad_api.py', 'w') as f:
    f.write(c)
print("Done")
