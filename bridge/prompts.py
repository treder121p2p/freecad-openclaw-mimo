#!/usr/bin/env python3
"""
Prompt Templates — task-specific промпты и few-shot примеры.
Адаптирует промпт под тип задачи для точного ответа модели.

Источник идей: https://habr.com/ru/articles/1072444/
"""


# === Few-shot: Boolean операции ===

FEWSHOT_BOOLEAN = """
## Примеры Boolean-операций:

### Вычитание (отверстие):
```python
base = h.box(50, 50, 20, name="Base")
hole = h.cylinder(10, 25, name="Hole")
h.move(hole, x=25, y=25, z=-2)
result = h.cut(base, hole, name="Base_With_Hole")
```

### Объединение (составная деталь):
```python
plate = h.box(60, 40, 5, name="Plate")
bracket = h.box(10, 40, 30, name="Bracket")
h.move(bracket, x=50, z=5)
result = h.fuse(plate, bracket, name="Assembly")
```

### Пересечение:
```python
cyl = h.cylinder(15, 40, name="Cylinder")
box = h.box(20, 20, 40, name="Box")
h.move(box, x=-10, y=-10)
result = h.intersect(cyl, box, name="Intersection")
```
"""

# === Few-shot: Placement и массивы ===

FEWSHOT_ARRAY = """
## Примеры массивов и размещения:

### Линейный массив цилиндров:
```python
for i in range(4):
    c = h.cylinder(3, 10, name=f"Peg_{i}")
    h.move(c, x=i*15, y=0, z=0)
```

### Поворот + перемещение:
```python
arm = h.box(50, 5, 5, name="Arm")
h.place(arm, x=0, y=0, z=20, rz=30)
```
"""

# === Few-shot: Составные детали по описанию ===

FEWSHOT_COMPOUND = """
## Примеры составных деталей:

### Пластина с отверстием:
"Основание 100x60x10 с отверстием r=15 по центру"
```python
base = h.box(100, 60, 10, name="Base")
hole = h.cylinder(15, 12, name="Hole")
h.move(hole, x=50, y=30, z=-1)
result = h.cut(base, hole, name="Base_With_Hole")
```

### Пластина с двумя штифтами:
```python
plate = h.box(80, 40, 5, name="Plate")
peg1 = h.cylinder(4, 10, name="Peg_1")
h.move(peg1, x=10, y=20, z=5)
peg2 = h.cylinder(4, 10, name="Peg_2")
h.move(peg2, x=70, y=20, z=5)
result = h.fuse(plate, peg1)
result = h.fuse(result, peg2)
```
"""

# === Few-shot: Фаски и скругления ===

FEWSHOT_MODIFIERS = """
## Примеры фасок и скруглений:

### Скругление рёбер:
```python
box = h.box(30, 20, 10, name="Box")
rounded = h.fillet(box, radius=2.0, name="Rounded_Box")
```

### Фаска:
```python
box = h.box(30, 20, 10, name="Box")
chamfered = h.chamfer(box, size=1.0, name="Chamfered_Box")
```
"""

# === Few-shot: Экспорт ===

FEWSHOT_EXPORT = """
## Примеры экспорта:

### Экспорт в STL:
```python
result = h.export_stl("/tmp/model.stl")
print(result)  # EXPORT_OK:/tmp/model.stl
```

### Экспорт в STEP:
```python
result = h.export_step("/tmp/model.step")
print(result)
```
"""


# === Task-specific системные промпты ===

PROMPT_BOOLEAN = """При boolean-операциях:
- ВСЕГДА создавай оба объекта (base + tool) отдельно
- Перемещай tool перед boolean если нужно
- h.cut(base, tool) — tool должен пересекать base
- После boolean проверяй результат через h.info()
"""

PROMPT_DRAWING = """Построение по описанию/чертежу:
- Определи основные формы (корпус, отверстия, пазы)
- Создавай отдельные примитивы для каждой формы
- Собирай через boolean
- Размеры в мм, уточняй если не даны
"""

PROMPT_PLACEMENT = """Размещение объектов:
- Используй h.place(obj, x, y, z, rx, ry, rz) для точного позиционирования
- Для массивов используй цикл for
- Центрируй по умолчанию (0,0,0)
"""

PROMPT_MODIFIERS = """Фаски и скругления:
- h.fillet(obj, radius) — скругление ВСЕХ рёбер
- h.chamfer(obj, size) — фаска ВСЕХ рёбер
- Для избирательного скругления — используй Part API напрямую
"""

# === Визуальный контроль (из статьи) ===

VISUAL_CHECK_PROMPT = """## ВИЗУАЛЬНЫЙ КОНТРОЛЬ (ОБЯЗАТЕЛЕН):
После выполнения кода ты ОБЯЗАН проверить результат:
1. Запроси скриншот текущего вида FreeCAD
2. Сравни с тем что просил пользователь
3. Если есть расхождения — исправь и повтори проверку

Это критически важно. 45% задач требуют правки после визуальной проверки.
Из 100 код-блоков, 65 идут на визуальный осмотр, и только 31% проходят без правок.
"""


def get_task_prompts(task_type, needs_boolean=False, needs_array=False, needs_modifiers=False):
    """Собрать релевантные промпты для задачи."""
    parts = []
    if needs_boolean:
        parts.append(PROMPT_BOOLEAN)
        parts.append(FEWSHOT_BOOLEAN)
    if needs_array:
        parts.append(PROMPT_PLACEMENT)
        parts.append(FEWSHOT_ARRAY)
    if needs_modifiers:
        parts.append(PROMPT_MODIFIERS)
        parts.append(FEWSHOT_MODIFIERS)
    if task_type == "drawing":
        parts.append(PROMPT_DRAWING)
        parts.append(FEWSHOT_COMPOUND)
    elif task_type == "modeling":
        parts.append(FEWSHOT_COMPOUND)
    parts.append(FEWSHOT_EXPORT)
    parts.append(VISUAL_CHECK_PROMPT)
    return "\n\n".join(parts)


def detect_task_features(user_message):
    """Определить какие промпты нужны для задачи."""
    msg = user_message.lower()
    needs_boolean = any(w in msg for w in [
        "отверсти", "дырк", "вырез", "вычесть", "cut", "hole",
        "объедини", "fuse", "соедини", "slit",
        "пересеч", "intersect"
    ])
    needs_array = any(w in msg for w in [
        "массив", "ряд", "повтор", "скопируй", "несколько",
        "4 шт", "5 шт", "6 шт", "штук"
    ])
    needs_modifiers = any(w in msg for w in [
        "фаска", "фаску", "скруглен", "скругли", "fillet", "chamfer",
        "закругл"
    ])
    return needs_boolean, needs_array, needs_modifiers
