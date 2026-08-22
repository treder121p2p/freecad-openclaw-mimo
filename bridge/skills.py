#!/usr/bin/env python3
"""
Skills Library — готовые паттерны для типичных CAD-операций.
Основано на: ghbalf/freecad-ai (skills system)
"""

SKILLS = {
    "gear": {
        "description": "Зубчатое колесо (модуль, зубья, ширина)",
        "params": {
            "module": "float — модуль зуба (определяет размер зубьев)",
            "teeth": "int — количество зубьев",
            "width": "float — ширина венца (мм)",
            "bore_diameter": "float — диаметр отверстия вала (мм, optional)",
        },
        "template": """
# Skill: Gear
import math
module = {module}
teeth = {teeth}
width = {width}
pitch_diameter = module * teeth
outer_diameter = pitch_diameter + 2 * module

# 1. Основной цилиндр (венец)
h.cylinder(radius=outer_diameter/2, height=width, name="Gear_Body")

# 2. Зубья
tooth_height = module * 2.2
tooth_width = module * math.pi * 0.4
center_r = pitch_diameter / 2
for i in range(teeth):
    angle = 2 * math.pi * i / teeth
    tx = center_r * math.cos(angle)
    ty = center_r * math.sin(angle)
    tooth = h.box(tooth_width, module * 0.8, tooth_height, name=f"tooth_{{i}}")
    h.place(tooth, x=tx, y=ty, z=width/2 - tooth_height/2, rz=math.degrees(angle))
    base = h.fuse(base, tooth, remove_old=True)

# 3. Отверстие вала (если задано)
bore_diameter = {bore_diameter}
if bore_diameter > 0:
    h.through_hole(base, 0, 0, bore_diameter/2, name="Bore")

h.info(base)
""",
    },

    "flange": {
        "description": "Фланец (OD, bore, толщина, болтовые отверстия)",
        "params": {
            "od": "float — наружный диаметр (мм)",
            "bore": "float — диаметр отверстия (мм)",
            "thickness": "float — толщина (мм)",
            "bolt_count": "int — количество болтовых отверстий",
            "bolt_circle_diameter": "float — диаметр болтовой окружности (мм)",
            "bolt_hole_diameter": "float — диаметр болтового отверстия (мм)",
        },
        "template": """
# Skill: Flange
import math
od = {od}
bore = {bore}
thickness = {thickness}
bolt_count = {bolt_count}
bcd = {bolt_circle_diameter}
bhd = {bolt_hole_diameter}

# 1. Основной диск
base = h.cylinder(radius=od/2, height=thickness, name="Flange_Disc")

# 2. Центральное отверстие
h.through_hole(base, 0, 0, bore/2, name="Bore")

# 3. Болтовые отверстия
for i in range(bolt_count):
    angle = 2 * math.pi * i / bolt_count
    bx = (bcd/2) * math.cos(angle)
    by = (bcd/2) * math.sin(angle)
    h.through_hole(base, bx, by, bhd/2, name=f"Bolt_{{i}}")

h.info(base)
""",
    },

    "bracket": {
        "description": "Кронштейн (ширина, длина, толщина, отверстия)",
        "params": {
            "width": "float — ширина (мм)",
            "length": "float — длина (мм)",
            "thickness": "float — толщина (мм)",
            "hole_radius": "float — радиус крепёжного отверстия (мм, optional)",
            "holes": "int — количество отверстий (optional, default 2)",
        },
        "template": """
# Skill: Bracket
width = {width}
length = {length}
thickness = {thickness}
hole_radius = {hole_radius}
holes = {holes}

# 1. Основная пластина
base = h.box(width, length, thickness, name="Bracket_Body")

# 2. Крепёжные отверстия
if hole_radius > 0 and holes > 0:
    margin = min(width, length) * 0.2
    spacing = (length - 2 * margin) / max(holes - 1, 1)
    for i in range(holes):
        cy = margin + i * spacing
        h.through_hole(base, width/2, cy, hole_radius, name=f"Hole_{{i}}")

h.info(base)
""",
    },

    "enclosure": {
        "description": "Корпус (ширина, длина, высота, толщина стенок)",
        "params": {
            "width": "float — ширина (мм)",
            "length": "float — длина (мм)",
            "height": "float — высота (мм)",
            "wall_thickness": "float — толщина стенок (мм)",
        },
        "template": """
# Skill: Enclosure (open-top box)
w = {width}
l = {length}
h_val = {height}
t = {wall_thickness}

# 1. Внешний параллелепипед
outer = h.box(w, l, h_val, name="Outer")

# 2. Внутренний вырез
inner = h.box(w - 2*t, l - 2*t, h_val - t, name="Inner_Cut")
h.move(inner, x=t, y=t, z=t)

# 3. Вычитание
base = h.cut(outer, inner, name="Enclosure", remove_old=True)

h.info(base)
""",
    },

    "shaft": {
        "description": "Вал (диаметр, длина, шпоночный паз)",
        "params": {
            "diameter": "float — диаметр вала (мм)",
            "length": "float — длина вала (мм)",
            "keyway_width": "float — ширина шпоночного паза (мм, optional)",
            "keyway_depth": "float — глубина шпоночного паза (мм, optional)",
        },
        "template": """
# Skill: Shaft with optional keyway
d = {diameter}
l = {length}
kw = {keyway_width}
kd = {keyway_depth}

# 1. Основной вал
base = h.cylinder(radius=d/2, height=l, name="Shaft")

# 2. Шпоночный паз (если задан)
if kw > 0 and kd > 0:
    keyway = h.box(kw, d, kd, name="Keyway")
    h.place(keyway, x=-kw/2, y=0, z=l - kd)
    base = h.cut(base, keyway, name="Shaft_With_Keyway", remove_old=True)

h.info(base)
""",
    },
}


def get_skills_description():
    """Описание всех skills для промпта."""
    lines = ["## SKILLS (reusable patterns):\n"]
    for name, info in SKILLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["params"].items())
        lines.append(f"- `{name}`({params}) — {info['description']}")
    lines.append("\nWhen user requests match a skill, use it instead of writing code from scratch.")
    return "\n".join(lines)


def execute_skill(skill_name, params, rpc_call_fn):
    """Выполнить skill через RPC."""
    if skill_name not in SKILLS:
        return {"error": f"Unknown skill: {skill_name}", "available": list(SKILLS.keys())}

    skill = SKILLS[skill_name]

    # Set defaults
    filled_params = {}
    for key, desc in skill["params"].items():
        if key in params:
            filled_params[key] = params[key]
        else:
            # Extract default from description
            if "optional" in desc.lower():
                filled_params[key] = 0
            elif "default" in desc.lower():
                try:
                    default_val = desc.split("default ")[-1].split(")")[0]
                    filled_params[key] = float(default_val) if "." in default_val else int(default_val)
                except:
                    filled_params[key] = 0
            else:
                filled_params[key] = 0

    # Generate code from template
    try:
        code = skill["template"].format(**filled_params)
    except KeyError as e:
        return {"error": f"Missing parameter: {e}"}

    # Execute
    try:
        result = rpc_call_fn('execute_code', [code])
        output = result.get('message', '') if isinstance(result, dict) else str(result)
        return {"success": True, "output": output, "skill": skill_name, "code": code}
    except Exception as e:
        return {"success": False, "error": str(e), "skill": skill_name, "code": code}
