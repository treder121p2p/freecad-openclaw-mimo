#!/usr/bin/env python3
"""
Report View Reader — чтение панели «Сообщения» FreeCAD через PySide6.
Используется для обратной связи: автоматически извлекает ошибки/предупреждения
из Report view и передаёт их в feedback loop.
"""

import json
import logging
import re

log = logging.getLogger("report_view")


def read_report_view(rpc_call_fn=None):
    """Прочитать содержимое Report view (панель «Сообщения») через PySide6.
    
    Если rpc_call_fn=None — выполняет RPC-вызов напрямую (избегает deadlock).
    Возвращает dict с:
      - total_lines: int
      - errors: list[str] — строки с ошибками
      - warnings: list[str] — строки с предупреждениями  
      - last_lines: list[str] — последние N строк
      - raw_len: int — длина полного лога
    """
    read_code = """
from PySide6 import QtWidgets
import FreeCADGui, json

main_win = FreeCADGui.getMainWindow()
if not main_win:
    print(json.dumps({"error": "no_main_window"}))
else:
    report_views = main_win.findChildren(QtWidgets.QTextEdit)
    content = ""
    for rv in report_views:
        if rv.objectName() == "Report view":
            content = rv.toPlainText()
            break
    
    lines = content.strip().split('\\n')
    errors = []
    warnings = []
    
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        low = line_s.lower()
        if any(k in low for k in ['error', 'exception', 'traceback', 'fault']):
            errors.append(line_s)
        elif any(k in low for k in ['warning', 'warn']):
            warnings.append(line_s)
    
    result = {
        'total_lines': len(lines),
        'errors': errors[-30:],
        'warnings': warnings[-30:],
        'last_lines': lines[-15:],
        'raw_len': len(content),
    }
    print(json.dumps(result, ensure_ascii=False))
"""
    try:
        if rpc_call_fn:
            raw = rpc_call_fn('execute_code', [read_code])
        else:
            # Direct RPC call (avoid nested deadlock)
            import http.client
            body = '<?xml version="1.0"?><methodCall><methodName>execute_code</methodName><params>'
            body += '<param><value><string>' + read_code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;') + '</string></value></param>'
            body += '</params></methodCall>'
            bb = body.encode('utf-8')
            c = http.client.HTTPConnection('localhost', 9875, timeout=30)
            c.request('POST', '/', bb, {'Content-Type': 'text/xml; charset=utf-8'})
            raw = c.getresponse().read().decode()
            c.close()
            # Parse XML response
            import re as _re
            m = _re.search(r'<string>(.*?)</string>', raw, _re.DOTALL)
            raw = {'message': m.group(1) if m else raw}
        
        msg = raw.get('message', '') if isinstance(raw, dict) else str(raw)
        
        # Extract JSON from RPC output
        json_start = msg.find('{')
        json_end = msg.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(msg[json_start:json_end])
            log.info(f"Report view: {data.get('total_lines', 0)} lines, "
                     f"{len(data.get('errors', []))} errors, "
                     f"{len(data.get('warnings', []))} warnings")
            return data
        else:
            log.warning(f"Could not parse Report view output: {msg[:200]}")
            return {"error": "parse_failed", "raw": msg[:500]}
    except Exception as e:
        log.error(f"Failed to read Report view: {e}")
        return {"error": str(e)}


def get_recent_errors(rpc_call_fn, max_errors=10):
    """Получить последние ошибки из Report view."""
    data = read_report_view(rpc_call_fn)
    return data.get('errors', [])[-max_errors:]


def get_error_summary(rpc_call_fn=None):
    """Краткую сводку ошибок из Report view для feedback loop."""
    data = read_report_view(rpc_call_fn)
    errors = data.get('errors', [])
    warnings = data.get('warnings', [])
    
    if not errors and not warnings:
        return None
    
    parts = []
    if errors:
        parts.append(f"**Errors ({len(errors)}):**")
        seen = set()
        unique_errors = []
        for e in errors:
            normalized = re.sub(r'^\d{2}:\d{2}:\d{2}\s+', '', e)
            if normalized not in seen:
                seen.add(normalized)
                unique_errors.append(e)
        for e in unique_errors[-5:]:
            parts.append(f"  - {e[:200]}")
    
    if warnings:
        parts.append(f"**Warnings ({len(warnings)}):**")
        for w in warnings[-3:]:
            parts.append(f"  - {w[:200]}")
    
    return "\n".join(parts)


def build_error_context_for_model(rpc_call_fn=None, user_request=""):
    """Построить контекст ошибок из Report view для передачи модели."""
    data = read_report_view(rpc_call_fn)
    errors = data.get('errors', [])
    warnings = data.get('warnings', [])
    
    if not errors:
        return ""
    
    context = "## FreeCAD Report View Errors\n\n"
    context += "The following errors were reported in FreeCAD's Messages panel:\n\n"
    
    for e in errors[-10:]:
        context += f"- {e[:300]}\n"
    
    if warnings:
        context += f"\nWarnings ({len(warnings)}):\n"
        for w in warnings[-5:]:
            context += f"- {w[:200]}\n"
    
    context += "\n**Fix these errors using h.* wrapper methods.**\n"
    context += "Do NOT use cadquery, Part, or raw FreeCAD API.\n"
    
    return context
