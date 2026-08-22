#!/usr/bin/env python3
"""
Error Feedback — структурированная обратная связь по ошибкам FreeCAD.
Основано на: ghbalf/freecad-ai (error self-correction loop, 30 turns max)
"""

import re
import logging

log = logging.getLogger("error_feedback")

# === Error Categories ===
ERROR_CATEGORIES = {
    "NameError": {
        "common_fixes": {
            "App": "Замени App на FreeCAD",
            "Part": "Добавь import Part",
            "FreeCAD": "Добавь import FreeCAD",
            "FreeCADGui": "Добавь import FreeCADGui",
            "Sketcher": "Добавь import Sketcher",
            "PartDesign": "Добавь import PartDesign",
            "h": "Wrapper h не инициализирован — выполни инициализацию wrapper",
            "doc": "Используй h._safe_doc() вместо прямого обращения к doc",
        },
        "pattern": r"name '(\w+)' is not defined",
    },
    "TypeError": {
        "common_fixes": {
            "positional": "Проверь количество аргументов — используй именованные параметры",
            "keyword": "Проверь имена параметров метода",
            "NoneType": "Передан None вместо объекта — проверь что объект создан",
            "unsupported operand": "Несовместимые типы для операции — приведи к нужному типу",
        },
        "pattern": r"TypeError: (.+)",
    },
    "AttributeError": {
        "common_fixes": {
            "'NoneType'": "Объект не существует — проверь документ и имена",
            "deleted object": "Объект был удалён — создай заново",
            "has no attribute": "Объект не имеет этого атрибута — проверь API",
            "ActiveView": "Нет активного вида — убедись что GUI запущен",
            "ActiveDocument": "Нет активного документа — создай документ",
        },
        "pattern": r"AttributeError: (.+)",
    },
    "ReferenceError": {
        "common_fixes": {
            "deleted object": "Объект удалён из документа — пересоздай",
        },
        "pattern": r"ReferenceError: (.+)",
    },
    "ValueError": {
        "common_fixes": {
            "negative": "Отрицательное значение недопустимо",
            "out of range": "Значение за пределами допустимого диапазона",
            "empty": "Пустая последовательность — проверь входные данные",
        },
        "pattern": r"ValueError: (.+)",
    },
    "SyntaxError": {
        "common_fixes": {
            "unexpected EOF": "Незакрытая скобка или кавычка",
            "invalid syntax": "Проверь синтаксис — отступы, двоеточия, скобки",
            "unexpected indent": "Проблема с отступами",
        },
        "pattern": r"SyntaxError: (.+)",
    },
    "RuntimeError": {
        "common_fixes": {
            "Shape": "Операция с геометрией не удалась — проверь параметры",
            "boolean": "Boolean операция не удалась — объекты не пересекаются",
            "recompute": "Ошибка recompute — проверь целостность документа",
        },
        "pattern": r"RuntimeError: (.+)",
    },
    "IndexError": {
        "common_fixes": {
            "out of range": "Индекс за пределами — проверь количество элементов",
        },
        "pattern": r"IndexError: (.+)",
    },
    "KeyError": {
        "common_fixes": {
            "not found": "Ключ не найден — проверь имена свойств",
        },
        "pattern": r"KeyError: (.+)",
    },
}


def analyze_error(error_output, code_context=""):
    """Анализ ошибки FreeCAD — возвращает структурированный ответ."""
    analysis = {
        "error_type": "Unknown",
        "error_message": "",
        "line_number": None,
        "category": None,
        "suggestion": "",
        "fix_code": None,
        "confidence": "low",
    }

    if not error_output:
        return analysis

    # Detect error type
    for etype, info in ERROR_CATEGORIES.items():
        if etype in error_output:
            analysis["error_type"] = etype
            analysis["category"] = etype

            # Match specific pattern
            m = re.search(info["pattern"], error_output)
            if m:
                analysis["error_message"] = m.group(1)[:200]

            # Find matching fix
            msg_lower = analysis["error_message"].lower()
            for key, suggestion in info["common_fixes"].items():
                if key.lower() in msg_lower or key.lower() in error_output.lower():
                    analysis["suggestion"] = suggestion
                    analysis["confidence"] = "high"
                    break

            if not analysis["suggestion"] and info["common_fixes"]:
                # Use first generic suggestion
                first_key = list(info["common_fixes"].keys())[0]
                analysis["suggestion"] = info["common_fixes"][first_key]
                analysis["confidence"] = "medium"
            break

    # Extract line number
    ln_match = re.search(r'line (\d+)', error_output)
    if ln_match:
        analysis["line_number"] = int(ln_match.group(1))

    # Extract code context around error
    if analysis["line_number"] and code_context:
        lines = code_context.split('\n')
        start = max(0, analysis["line_number"] - 3)
        end = min(len(lines), analysis["line_number"] + 2)
        analysis["code_context"] = '\n'.join(
            f"{'>>>' if i+1 == analysis['line_number'] else '   '} {i+1}: {l}"
            for i, l in enumerate(lines[start:end], start)
        )

    # Auto-generate fix hints
    analysis["fix_hint"] = _generate_fix_hint(analysis)

    return analysis


def _generate_fix_hint(analysis):
    """Генерация подсказки для исправления."""
    etype = analysis["error_type"]
    msg = analysis["error_message"]

    if etype == "NameError":
        if "App" in msg:
            return "Замени 'App' на 'FreeCAD' в коде"
        if "FreeCAD" in msg:
            return "Добавь 'import FreeCAD' в начало кода"
        if "h" in msg:
            return "Убедись что wrapper h инициализирован: h = FreeCADHelper(doc)"
        return f"Определи переменную '{msg}' или добавь import"

    elif etype == "TypeError":
        if "positional" in msg:
            return "Используй именованные параметры: h.method(obj, x=0, y=0)"
        return "Проверь типы и количество аргументов"

    elif etype == "AttributeError":
        if "NoneType" in msg:
            return "Объект не найден — проверь h.list_objects() для списка"
        if "deleted" in msg:
            return "Объект был удалён — создай заново через h.box/h.cylinder"
        return "Проверь доступные методы через h.list_objects()"

    elif etype == "ReferenceError":
        return "Объект удалён из документа — пересоздай"

    elif etype == "RuntimeError":
        if "Shape" in msg or "boolean" in msg.lower():
            return "Boolean операция не удалась — убедись что объекты пересекаются"
        return "Проверь параметры операции"

    return "Проверь код и попробуй исправить ошибку"


def build_error_context(error_output, code, attempt, max_attempts):
    """Построить контекст ошибки для передачи модели."""
    analysis = analyze_error(error_output, code)

    context = f"## ERROR (attempt {attempt}/{max_attempts})\n\n"
    context += f"**Type:** {analysis['error_type']}\n"
    context += f"**Message:** {analysis['error_message']}\n"

    if analysis["line_number"]:
        context += f"**Line:** {analysis['line_number']}\n"

    if analysis.get("code_context"):
        context += f"\n**Code context:**\n```\n{analysis['code_context']}\n```\n"

    context += f"\n**Suggestion:** {analysis['suggestion']}\n"
    context += f"**Fix hint:** {analysis['fix_hint']}\n"

    context += "\n**YOUR TASK:** Fix the code and return corrected JSON with action=code.\n"
    context += "Do NOT ask questions. Just fix the error and output corrected code.\n"

    return context, analysis


def build_verification_context(screenshot_b64, user_request, step_description, view_angle="Iso"):
    """Построить контекст для визуальной верификации."""
    return (
        f"## VISUAL VERIFICATION\n\n"
        f"**User request:** {user_request}\n"
        f"**Current step:** {step_description}\n"
        f"**View angle:** {view_angle}\n\n"
        f"Compare the screenshot with the user's request.\n"
        f"Reply JSON: {{\"match\": true/false, \"issues\": [...], \"summary\": \"...\"}}"
    )


def categorize_error_severity(error_output):
    """Определить серьёжность ошибки."""
    critical_keywords = ['Segmentation', 'SIGKILL', 'crash', 'fatal', 'out of memory']
    high_keywords = ['ReferenceError', 'deleted object', 'ActiveView']
    medium_keywords = ['TypeError', 'AttributeError', 'ValueError']
    low_keywords = ['NameError', 'SyntaxError', 'IndentationError']

    for kw in critical_keywords:
        if kw.lower() in error_output.lower():
            return "critical"
    for kw in high_keywords:
        if kw in error_output:
            return "high"
    for kw in medium_keywords:
        if kw in error_output:
            return "medium"
    for kw in low_keywords:
        if kw in error_output:
            return "low"
    return "unknown"
