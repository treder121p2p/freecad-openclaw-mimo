#!/usr/bin/env python3
"""
Typed Tools — типизированные инструменты для FreeCAD.
Вместо голого execute_code — безопасные, структурированные вызовы.
Основано на: ghbalf/freecad-ai (50 tools) + neka-nat/freecad-mcp (11 tools)
"""

import json
import logging

log = logging.getLogger("typed_tools")

# === Tool Registry ===
TOOLS = {
    "create_box": {
        "description": "Создать параллелепипед",
        "params": {"length": "float (mm)", "width": "float (mm)", "height": "float (mm)", "name": "str (optional)"},
    },
    "create_cylinder": {
        "description": "Создать цилиндр",
        "params": {"radius": "float (mm)", "height": "float (mm)", "name": "str (optional)"},
    },
    "create_sphere": {
        "description": "Создать сферу",
        "params": {"radius": "float (mm)", "name": "str (optional)"},
    },
    "create_cone": {
        "description": "Создать конус",
        "params": {"radius1": "float (mm)", "radius2": "float (mm)", "height": "float (mm)", "name": "str (optional)"},
    },
    "boolean_cut": {
        "description": "Вычитание (Boolean Cut)",
        "params": {"base": "str (object name)", "tool": "str (object name)", "name": "str (optional)"},
    },
    "boolean_fuse": {
        "description": "Объединение (Boolean Union)",
        "params": {"obj1": "str (object name)", "obj2": "str (object name)", "name": "str (optional)"},
    },
    "boolean_intersect": {
        "description": "Пересечение (Boolean Common)",
        "params": {"obj1": "str (object name)", "obj2": "str (object name)", "name": "str (optional)"},
    },
    "move_object": {
        "description": "Переместить объект",
        "params": {"object": "str (name)", "x": "float", "y": "float", "z": "float"},
    },
    "rotate_object": {
        "description": "Повернуть объект",
        "params": {"object": "str (name)", "rx": "float (deg)", "ry": "float (deg)", "rz": "float (deg)"},
    },
    "place_object": {
        "description": "Переместить + повернуть",
        "params": {"object": "str (name)", "x": "float", "y": "float", "z": "float", "rx": "float", "ry": "float", "rz": "float"},
    },
    "get_object_info": {
        "description": "Информация об объекте",
        "params": {"object": "str (name)"},
    },
    "list_objects": {
        "description": "Список всех объектов",
        "params": {},
    },
    "delete_object": {
        "description": "Удалить объект",
        "params": {"object": "str (name)"},
    },
    "clear_document": {
        "description": "Очистить документ",
        "params": {},
    },
    "get_screenshot": {
        "description": "Скриншот вида",
        "params": {"view": "str (Front/Top/Right/Left/Back/Bottom/Iso)"},
    },
    "fillet_edges": {
        "description": "Скруглить рёбра",
        "params": {"object": "str (name)", "radius": "float (mm)"},
    },
    "chamfer_edges": {
        "description": "Снять фаску",
        "params": {"object": "str (name)", "size": "float (mm)"},
    },
    "export_stl": {
        "description": "Экспорт в STL",
        "params": {"path": "str (optional, default /tmp/export.stl)"},
    },
    "export_step": {
        "description": "Экспорт в STEP",
        "params": {"path": "str (optional, default /tmp/export.step)"},
    },
    "through_hole": {
        "description": "Сквозное отверстие",
        "params": {"base": "str (name)", "cx": "float", "cy": "float", "radius": "float (mm)", "name": "str (optional)"},
    },
}


def get_tools_description():
    """Описание всех инструментов для промпта модели."""
    lines = ["## AVAILABLE TOOLS (use these instead of raw code when possible):\n"]
    for name, info in TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["params"].items()) if info["params"] else "none"
        lines.append(f"- `{name}`({params}) — {info['description']}")
    lines.append("\n### When to use tools vs code:")
    lines.append("- Simple primitives (box, cylinder, sphere) → use tools")
    lines.append("- Boolean ops between named objects → use tools")
    lines.append("- Complex operations (arrays, sketches, sweeps) → use execute_code with h.*")
    lines.append("- Always prefer tools when available — they are safer and return structured results")
    return "\n".join(lines)


def execute_tool(tool_name, params, rpc_call_fn):
    """Выполнить типизированный инструмент через RPC."""
    if tool_name not in TOOLS:
        return {"error": f"Unknown tool: {tool_name}", "available": list(TOOLS.keys())}

    # Build Python code for the tool
    code = _build_tool_code(tool_name, params)
    if code is None:
        return {"error": f"Cannot build code for tool: {tool_name}"}

    try:
        result = rpc_call_fn('execute_code', [code])
        output = result.get('message', '') if isinstance(result, dict) else str(result)

        # Parse output
        if 'Error' in output or 'Traceback' in output:
            error_info = parse_error(output, code)
            return {"success": False, "error": error_info, "raw_output": output[:500]}

        return {"success": True, "output": output, "tool": tool_name}
    except Exception as e:
        return {"success": False, "error": {"type": "Exception", "message": str(e)}, "tool": tool_name}


def _build_tool_code(tool_name, params):
    """Построить Python-код для инструмента."""
    p = params  # shorthand

    if tool_name == "create_box":
        name = p.get("name", "Box")
        return (
            f'h.box(length={p.get("length", 10)}, width={p.get("width", 10)}, '
            f'height={p.get("height", 10)}, name="{name}"); '
            f'print("OK:" + "{name}")'
        )

    elif tool_name == "create_cylinder":
        name = p.get("name", "Cylinder")
        return (
            f'h.cylinder(radius={p.get("radius", 5)}, height={p.get("height", 10)}, '
            f'name="{name}"); print("OK:" + "{name}")'
        )

    elif tool_name == "create_sphere":
        name = p.get("name", "Sphere")
        return f'h.sphere(radius={p.get("radius", 10)}, name="{name}"); print("OK:" + "{name}")'

    elif tool_name == "create_cone":
        name = p.get("name", "Cone")
        return (
            f'h.cone(radius1={p.get("radius1", 5)}, radius2={p.get("radius2", 0)}, '
            f'height={p.get("height", 10)}, name="{name}"); print("OK:" + "{name}")'
        )

    elif tool_name == "boolean_cut":
        base = p.get("base", "Base")
        tool = p.get("tool", "Tool")
        name = p.get("name", f"{base}_cut_{tool}")
        return f'h.cut({base}, {tool}, name="{name}"); print("OK:" + "{name}")'

    elif tool_name == "boolean_fuse":
        o1 = p.get("obj1", "Obj1")
        o2 = p.get("obj2", "Obj2")
        name = p.get("name", f"{o1}_fuse_{o2}")
        return f'h.fuse({o1}, {o2}, name="{name}"); print("OK:" + "{name}")'

    elif tool_name == "boolean_intersect":
        o1 = p.get("obj1", "Obj1")
        o2 = p.get("obj2", "Obj2")
        name = p.get("name", f"{o1}_and_{o2}")
        return f'h.intersect({o1}, {o2}, name="{name}"); print("OK:" + "{name}")'

    elif tool_name == "move_object":
        obj = p.get("object", "Obj")
        return (
            f'h.move({obj}, x={p.get("x", 0)}, y={p.get("y", 0)}, z={p.get("z", 0)}); '
            f'print("OK:moved {obj}")'
        )

    elif tool_name == "rotate_object":
        obj = p.get("object", "Obj")
        return (
            f'h.rotate({obj}, rx={p.get("rx", 0)}, ry={p.get("ry", 0)}, rz={p.get("rz", 0)}); '
            f'print("OK:rotated {obj}")'
        )

    elif tool_name == "place_object":
        obj = p.get("object", "Obj")
        return (
            f'h.place({obj}, x={p.get("x", 0)}, y={p.get("y", 0)}, z={p.get("z", 0)}, '
            f'rx={p.get("rx", 0)}, ry={p.get("ry", 0)}, rz={p.get("rz", 0)}); '
            f'print("OK:placed {obj}")'
        )

    elif tool_name == "get_object_info":
        obj = p.get("object", "Obj")
        return f'import json; info = h.info({obj}); print(json.dumps(info))'

    elif tool_name == "list_objects":
        return 'import json; print(json.dumps(h.list_objects()))'

    elif tool_name == "delete_object":
        obj = p.get("object", "Obj")
        return f'h._safe_doc().removeObject("{obj}"); h._safe_doc().recompute(); print("OK:deleted {obj}")'

    elif tool_name == "clear_document":
        return 'h.clear(); print("OK:cleared")'

    elif tool_name == "get_screenshot":
        view = p.get("view", "Iso")
        view_map = {
            "Front": "0,0,0", "Top": "0,90,0", "Right": "90,0,0",
            "Back": "0,180,0", "Left": "-90,0,0", "Bottom": "0,-90,0",
            "Iso": "45,35,0",
        }
        angles = view_map.get(view, "45,35,0")
        return (
            f'import FreeCADGui; '
            f'FreeCADGui.ActiveDocument.ActiveView.view{view}(); '
            f'import tempfile, os; '
            f'path = os.path.join(tempfile.gettempdir(), "view_{view.lower()}.png"); '
            f'FreeCADGui.ActiveDocument.ActiveView.saveImage(path, 800, 600, "PNG"); '
            f'print("SCREENSHOT:" + path)'
        )

    elif tool_name == "fillet_edges":
        obj = p.get("object", "Obj")
        r = p.get("radius", 2.0)
        return f'h.fillet({obj}, radius={r}); print("OK:filleted {obj}")'

    elif tool_name == "chamfer_edges":
        obj = p.get("object", "Obj")
        s = p.get("size", 1.0)
        return f'h.chamfer({obj}, size={s}); print("OK:chamfered {obj}")'

    elif tool_name == "export_stl":
        path = p.get("path", "/tmp/export.stl")
        return f'print(h.export_stl("{path}"))'

    elif tool_name == "export_step":
        path = p.get("path", "/tmp/export.step")
        return f'print(h.export_step("{path}"))'

    elif tool_name == "through_hole":
        base = p.get("base", "Base")
        name = p.get("name", "Hole")
        return (
            f'h.through_hole({base}, cx={p.get("cx", 0)}, cy={p.get("cy", 0)}, '
            f'radius={p.get("radius", 5)}, name="{name}"); print("OK:" + "{name}")'
        )

    return None


def parse_error(output, code=""):
    """Парсинг ошибки FreeCAD — структурированный ответ для модели."""
    error_info = {
        "type": "Unknown",
        "message": "",
        "line": None,
        "suggestion": "",
    }

    lines = output.split("\n")
    for line in lines:
        line = line.strip()

        # Python error types
        if "NameError" in line:
            error_info["type"] = "NameError"
            var = line.split("name '")[-1].split("'")[0] if "'" in line else ""
            if var == "App":
                error_info["suggestion"] = "Используй FreeCAD вместо App"
            elif var == "Part":
                error_info["suggestion"] = "Импортируй Part: import Part"
            else:
                error_info["suggestion"] = f"Переменная '{var}' не определена. Проверь импорты и имена."

        elif "TypeError" in line:
            error_info["type"] = "TypeError"
            if "positional" in line and "were given" in line:
                error_info["suggestion"] = "Неправильное количество аргументов. Проверь сигнатуру метода."
            elif "unexpected keyword" in line:
                error_info["suggestion"] = "Неожиданный именованный аргумент. Проверь имена параметров."
            else:
                error_info["suggestion"] = "Несовместимые типы данных. Проверь типы аргументов."

        elif "AttributeError" in line:
            error_info["type"] = "AttributeError"
            if "'NoneType'" in line:
                error_info["suggestion"] = "Объект не существует. Проверь документ и имена объектов."
            elif "deleted object" in line:
                error_info["suggestion"] = "Объект был удалён. Создай заново или проверь ссылки."
            else:
                error_info["suggestion"] = "Объект не имеет этого атрибута/метода."

        elif "ReferenceError" in line:
            error_info["type"] = "ReferenceError"
            if "deleted object" in line:
                error_info["suggestion"] = "Объект удалён из документа. Создай заново."

        elif "ValueError" in line:
            error_info["type"] = "ValueError"
            error_info["suggestion"] = "Недопустимое значение. Проверь диапазоны и единицы."

        elif "SyntaxError" in line:
            error_info["type"] = "SyntaxError"
            error_info["suggestion"] = "Синтаксическая ошибка в Python коде. Проверь отступы и скобки."

        elif "RuntimeError" in line:
            error_info["type"] = "RuntimeError"
            if "Shape" in line:
                error_info["suggestion"] = "Операция с формой не удалась. Проверь геометрию."
            else:
                error_info["suggestion"] = "Ошибка выполнения. Проверь параметры."

        elif "IndexError" in line:
            error_info["type"] = "IndexError"
            error_info["suggestion"] = "Выход за границы. Проверь индексы и размеры."

    # Extract error message
    for line in lines:
        if "Error:" in line or "error:" in line:
            error_info["message"] = line.strip()[:300]
            break

    # Extract line number
    for line in lines:
        if "line " in line and "," in line:
            try:
                ln = line.split("line ")[1].split(",")[0].strip()
                error_info["line"] = int(ln)
            except:
                pass

    return error_info
