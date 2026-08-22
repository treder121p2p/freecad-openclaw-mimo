#!/usr/bin/env python3
"""
Enhanced Logging — расширенное логирование FreeCAD.
Собирает логи из всех источников, парсит по уровням,
формирует контекст для модели после каждого шага.
"""

import os
import re
import time
import logging

log = logging.getLogger("enhanced_logging")

# Источники логов FreeCAD
LOG_SOURCES = [
    "/var/log/freecad/freecad.log",
    "/var/log/freecad/mcp_addon.log",
    "/var/log/freecad/bridge.log",
    "/var/log/freecad/rpc_startup.log",
]

# Паттерны ошибок FreeCAD
ERROR_PATTERNS = [
    (r"(?i)\berror\b", "ERROR"),
    (r"(?i)\btraceback\b", "TRACEBACK"),
    (r"(?i)\bexception\b", "EXCEPTION"),
    (r"(?i)\bnameerror\b", "NAME_ERROR"),
    (r"(?i)\bvalueerror\b", "VALUE_ERROR"),
    (r"(?i)\bsyntaxerror\b", "SYNTAX_ERROR"),
    (r"(?i)\btypeerror\b", "TYPE_ERROR"),
    (r"(?i)\battributeerror\b", "ATTRIBUTE_ERROR"),
    (r"(?i)\bruntimeerror\b", "RUNTIME_ERROR"),
    (r"(?i)\bkeyerror\b", "KEY_ERROR"),
    (r"(?i)\boutofmemoryerror\b", "OUT_OF_MEMORY"),
    (r"(?i)\bfatal\b", "FATAL"),
    (r"(?i)\bcritical\b", "CRITICAL"),
    (r"(?i)\bsegmentation\b", "SEGFAULT"),
    (r"(?i)\bfailed\b", "FAILURE"),
    (r"(?i)\bcannot\b.*\bimport\b", "IMPORT_ERROR"),
    (r"(?i)\bno module named\b", "MODULE_NOT_FOUND"),
    (r"(?i)\bShape\s*isValid\s*:\s*False", "INVALID_SHAPE"),
    (r"(?i)\brecompute.*fail", "RECOMPUTE_FAIL"),
    (r"(?i)\bboolean.*fail", "BOOLEAN_FAIL"),
]

WARNING_PATTERNS = [
    (r"(?i)\bwarning\b", "WARNING"),
    (r"(?i)\bdeprecated\b", "DEPRECATED"),
    (r"(?i)\bslow\b", "PERFORMANCE"),
    (r"(?i)\btimeout\b", "TIMEOUT"),
]


def read_log_file(path, max_lines=50):
    """Прочитать последние строки из файла лога."""
    try:
        if not os.path.exists(path):
            return []
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-max_lines:] if l.strip()]
    except Exception as e:
        log.debug(f"Cannot read {path}: {e}")
        return []


def classify_line(line):
    """Классифицировать строку лога по уровню."""
    for pattern, level in ERROR_PATTERNS:
        if re.search(pattern, line):
            return "error", level
    for pattern, level in WARNING_PATTERNS:
        if re.search(pattern, line):
            return "warning", level
    return "info", None


def get_all_logs(max_per_source=30):
    """Собрать логи из всех источников с классификацией."""
    all_logs = []
    for src in LOG_SOURCES:
        lines = read_log_file(src, max_per_source)
        if lines:
            for line in lines:
                severity, error_type = classify_line(line)
                all_logs.append({
                    "source": os.path.basename(src),
                    "line": line,
                    "severity": severity,
                    "error_type": error_type,
                })
    return all_logs


def get_error_summary(max_logs=20):
    """Получить краткую сводку ошибок."""
    logs = get_all_logs()
    errors = [l for l in logs if l["severity"] == "error"]
    warnings = [l for l in logs if l["severity"] == "warning"]

    summary = {
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [],
        "warnings": [],
    }

    # Группируем ошибки по типу
    error_groups = {}
    for e in errors[:max_logs]:
        etype = e["error_type"] or "UNKNOWN"
        if etype not in error_groups:
            error_groups[etype] = []
        error_groups[etype].append(e["line"][-200:])  # последние 200 символов

    for etype, elines in error_groups.items():
        summary["errors"].append({
            "type": etype,
            "count": len(elines),
            "sample": elines[-1],  # последняя ошибка этого типа
        })

    for w in warnings[-5:]:
        summary["warnings"].append(w["line"][-150:])

    return summary


def get_context_for_model(after_execution=True, step_output=""):
    """Построить лог-контекст для модели.

    Args:
        after_execution: True если вызывается после выполнения кода
        step_output: вывод текущего шага
    """
    summary = get_error_summary()

    lines = []

    if step_output:
        # Парсим вывод на ошибки
        output_errors = []
        for pattern, etype in ERROR_PATTERNS:
            for m in re.finditer(pattern, step_output):
                # Контекст вокруг совпадения
                start = max(0, m.start() - 100)
                end = min(len(step_output), m.end() + 200)
                output_errors.append({
                    "type": etype,
                    "context": step_output[start:end].strip()
                })

        if output_errors:
            lines.append("## Ошибки в выводе кода:")
            for oe in output_errors[:3]:
                lines.append(f"  [{oe['type']}] {oe['context'][:300]}")

    # Ошибки из логов FreeCAD
    if summary["error_count"] > 0:
        lines.append(f"\n## Ошибки FreeCAD ({summary['error_count']}):")
        for err in summary["errors"][:3]:
            lines.append(f"  [{err['type']}] (×{err['count']}) {err['sample'][:200]}")

    if summary["warning_count"] > 0:
        lines.append(f"\n## Предупреждения ({summary['warning_count']}):")
        for w in summary["warnings"][:2]:
            lines.append(f"  {w[:150]}")

    if not lines:
        if after_execution:
            lines.append("## Логи: ошибок не обнаружено ✅")
        else:
            lines.append("## Логи: все чисто ✅")

    return "\n".join(lines)


def get_recent_activity(lines=10):
    """Получить последние события из логов (для общего контекста)."""
    all_logs = get_all_logs(max_per_source=lines)
    if not all_logs:
        return "Нет недавней активности в логах."

    result = ["## Последняя активность:"]
    for entry in all_logs[-lines:]:
        icon = "🔴" if entry["severity"] == "error" else \
               "🟡" if entry["severity"] == "warning" else "⚪"
        result.append(f"  {icon} [{entry['source']}] {entry['line'][-150:]}")

    return "\n".join(result)
