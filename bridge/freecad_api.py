#!/usr/bin/env python3
"""
FreeCAD High-Level API — семантическая обёртка поверх Part/RPC
Идея: вместо голого FreeCAD Python API, модель генерирует короткий код
через эти методы. Безопасно, семантически понятно, легко расширять.

Основано на подходе из статьи:
https://habr.com/ru/articles/1072444/
(ИИ-агент внутри КОМПАС-3D: пишет код, строит деталь и проверяет результат)
"""

import json


# === Генерация wrapper-кода для подстановки в exec контекст ===

WRAPPER_HEADER = '''
import FreeCAD
import Part
import math

doc = FreeCAD.activeDocument() or FreeCAD.newDocument("AIDoc")

class FreeCADHelper:
    """Высокоуровневая обёртка для безопасного моделирования."""

    def __init__(self, doc):
        self.doc = doc
        self._objects = []

    def _add(self, obj):
        self.doc.recompute()
        return obj

    def box(self, length=10, width=10, height=10, name=None):
        """Создать параллелепипед (мм)."""
        b = self.doc.addObject("Part::Box", name or f"Box_{len(self._objects)}")
        b.Length = float(length)
        b.Width = float(width)
        b.Height = float(height)
        self._objects.append(b)
        return self._add(b)

    def cylinder(self, radius=5, height=20, name=None):
        """Создать цилиндр (мм)."""
        c = self.doc.addObject("Part::Cylinder", name or f"Cyl_{len(self._objects)}")
        c.Radius = float(radius)
        c.Height = float(height)
        self._objects.append(c)
        return self._add(c)

    def sphere(self, radius=10, name=None):
        """Создать сферу (мм)."""
        s = self.doc.addObject("Part::Sphere", name or f"Sphere_{len(self._objects)}")
        s.Radius = float(radius)
        self._objects.append(s)
        return self._add(s)

    def cone(self, radius1=5, radius2=0, height=15, name=None):
        """Создать конус (мм)."""
        c = self.doc.addObject("Part::Cone", name or f"Cone_{len(self._objects)}")
        c.Radius1 = float(radius1)
        c.Radius2 = float(radius2)
        c.Height = float(height)
        self._objects.append(c)
        return self._add(c)

    def torus(self, radius1=10, radius2=3, name=None):
        """Создать тор (мм). radius1=большой, radius2=малый."""
        t = self.doc.addObject("Part::Torus", name or f"Torus_{len(self._objects)}")
        t.Radius1 = float(radius1)
        t.Radius2 = float(radius2)
        self._objects.append(t)
        return self._add(t)

    def move(self, obj, x=0, y=0, z=0):
        """Переместить объект на (x, y, z) мм."""
        obj.Placement.Base = FreeCAD.Vector(float(x), float(y), float(z))
        self.doc.recompute()
        return obj

    def rotate(self, obj, rx=0, ry=0, rz=0):
        """Повернуть объект (углы Эйлера в градусах)."""
        obj.Placement.Rotation = FreeCAD.Rotation(float(rx), float(ry), float(rz))
        self.doc.recompute()
        return obj

    def place(self, obj, x=0, y=0, z=0, rx=0, ry=0, rz=0):
        """Переместить и повернуть за один вызов."""
        obj.Placement = FreeCAD.Placement(
            FreeCAD.Vector(float(x), float(y), float(z)),
            FreeCAD.Rotation(float(rx), float(ry), float(rz))
        )
        self.doc.recompute()
        return obj

    def fuse(self, obj1, obj2, name=None):
        """Объединение (Boolean Union)."""
        result = obj1.Shape.fuse(obj2.Shape)
        feat = self.doc.addObject("Part::Feature", name or f"Fuse_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        return self._add(feat)

    def cut(self, base, tool, name=None):
        """Вычитание (Boolean Cut)."""
        result = base.Shape.cut(tool.Shape)
        feat = self.doc.addObject("Part::Feature", name or f"Cut_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        return self._add(feat)

    def intersect(self, obj1, obj2, name=None):
        """Пересечение (Boolean Common)."""
        result = obj1.Shape.common(obj2.Shape)
        feat = self.doc.addObject("Part::Feature", name or f"Intersect_{len(self._objects)}")
        feat.Shape = result
        self._objects.append(feat)
        return self._add(feat)

    def fillet(self, obj, radius=2.0, name=None):
        """Скруглить все рёбра объекта."""
        fillet = self.doc.addObject("Part::Fillet", name or f"Fillet_{len(self._objects)}")
        fillet.Base = obj
        fillet.Edges = [(i, float(radius), float(radius)) for i in range(len(obj.Shape.Edges))]
        self._objects.append(fillet)
        return self._add(fillet)

    def chamfer(self, obj, size=1.0, name=None):
        """Снять фаску со всех рёбер."""
        chamfer = self.doc.addObject("Part::Chamfer", name or f"Chamfer_{len(self._objects)}")
        chamfer.Base = obj
        chamfer.Size = float(size)
        self._objects.append(chamfer)
        return self._add(chamfer)

    def info(self, obj):
        """Информация об объекте: объём, площадь, габариты."""
        bb = obj.Shape.BoundBox
        return {
            "name": obj.Name,
            "type": obj.TypeId,
            "volume_mm3": round(obj.Shape.Volume, 2),
            "area_mm2": round(obj.Shape.Area, 2),
            "bbox": {
                "x": [round(bb.XMin, 2), round(bb.XMax, 2)],
                "y": [round(bb.YMin, 2), round(bb.YMax, 2)],
                "z": [round(bb.ZMin, 2), round(bb.ZMax, 2)],
            }
        }

    def list_objects(self):
        """Список всех объектов в документе."""
        return [
            {"name": o.Name, "type": o.TypeId,
             "pos": str(o.Placement.Base) if hasattr(o, "Placement") else "N/A"}
            for o in self.doc.Objects
        ]

    def clear(self):
        """Удалить все объекты."""
        for obj in self.doc.Objects[:]:
            self.doc.removeObject(obj.Name)
        self._objects.clear()
        self.doc.recompute()

    def export_stl(self, path="/tmp/export.stl"):
        """Экспорт в STL."""
        import Mesh
        shapes = [o for o in self.doc.Objects if hasattr(o, "Shape")]
        if shapes:
            Mesh.export(shapes, path)
            return f"EXPORT_OK:{path}"
        return "EXPORT_ERROR:No shapes"

    def export_step(self, path="/tmp/export.step"):
        """Экспорт в STEP."""
        import Import
        shapes = [o for o in self.doc.Objects if hasattr(o, "Shape")]
        if shapes:
            Import.export(shapes, path)
            return f"EXPORT_OK:{path}"
        return "EXPORT_ERROR:No shapes"


h = FreeCADHelper(doc)
'''

# Краткий промпт для модели — ссылается на wrapper
WRAPPER_PROMPT_ADDITION = """
## FREECAD HELPER API (ИСПОЛЬЗУЙ ЭТИ МЕТОДЫ):

Вместо голого FreeCAD API, используй объект `h` (FreeCADHelper):

```python
# Примеры:
h.box(length=50, width=30, height=10, name="Base")
h.cylinder(radius=15, height=40, name="Shaft")
h.move(obj2, x=25, y=15, z=10)
h.fuse(obj1, obj2)           # объединение
h.cut(base, tool)            # вычитание
h.fillet(obj, radius=2)      # скругление
h.chamfer(obj, size=1)       # фаска
h.info(obj)                  # объём, площадь, габариты
h.list_objects()             # список объектов
h.clear()                    # удалить всё
h.export_stl("/tmp/model.stl")
```

ВАЖНО:
- Все единицы в МИЛЛИМЕТРАХ
- После каждого шага h автоматически делает recompute
- Используй name= для понятных имён объектов
- h.box() возвращает объект — сохраняй в переменные: `base = h.box(...)`
"""


def get_wrapper_code():
    """Возвращает код wrapper-класса для выполнения в FreeCAD."""
    return WRAPPER_HEADER


def get_prompt_addition():
    """Возвращает дополнение к системному промпту с описанием wrapper API."""
    return WRAPPER_PROMPT_ADDITION
