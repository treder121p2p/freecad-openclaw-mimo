#!/usr/bin/env python3
"""
FreeCAD AI Bridge v2.0 — ReAct-agent with model orchestration.
Based on: https://habr.com/ru/articles/1072444/
"""
import json, os, sys, http.client, re, time, signal, threading
import traceback, logging, base64, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from freecad_api import get_wrapper_code, get_prompt_addition
from task_manager import TaskManager
from model_router import select_model, get_system_prompt_for_model, MODELS
from enhanced_logging import get_context_for_model, get_error_summary, get_recent_activity
from prompts import get_task_prompts, detect_task_features, VISUAL_CHECK_PROMPT, FALLBACK_TEMPLATES
from typed_tools import get_tools_description, execute_tool, parse_error
from error_feedback import analyze_error, build_error_context, categorize_error_severity
from report_view import read_report_view, get_error_summary as get_report_errors, build_error_context_for_model
from multi_view import capture_multi_view, capture_compare_views, screenshots_to_base64, build_multi_view_comparison, verify_step
from skills import get_skills_description, execute_skill, SKILLS

# --- Config ---
POLZA_HOST = os.environ.get("POLZA_HOST", "api.polza.ai")
POLZA_PORT = int(os.environ.get("POLZA_PORT", "443"))
POLZA_API_KEY = os.environ.get("POLZA_API_KEY", "")
if not POLZA_API_KEY:
    for p in ["/opt/freecad/.polza_key", "/root/.polza_key", os.path.expanduser("~/.polza_key")]:
        try:
            with open(p) as f: POLZA_API_KEY = f.read().strip()
            if POLZA_API_KEY: break
        except: pass
if not POLZA_API_KEY:
    print("FATAL: No POLZA_API_KEY", file=sys.stderr); sys.exit(1)

POLZA_MODEL = os.environ.get("POLZA_MODEL", "xiaomi/mimo-v2.5")
POLZA_PATH = os.environ.get("POLZA_PATH", "/api/v1/chat/completions")
FREECAD_RPC_HOST = os.environ.get("FREECAD_RPC_HOST", "localhost")
FREECAD_RPC_PORT = int(os.environ.get("FREECAD_RPC_PORT", "9875"))
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "9877"))
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")
ENABLE_SCREENSHOT = os.environ.get("ENABLE_SCREENSHOT", "1") == "1"
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))
MAX_REACT_STEPS = int(os.environ.get("MAX_REACT_STEPS", "8"))
ENABLE_VISUAL_CHECK = os.environ.get("ENABLE_VISUAL_CHECK", "1") == "1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bridge")

task_manager = TaskManager(ttl_seconds=3600, max_tasks=50)
wrapper_initialized = False

# --- System Prompt ---
BASE_SYSTEM_PROMPT = """
## ТЫ — AI-ассистент для 3D-моделирования в FreeCAD.

### ГЛАВНОЕ ПРАВИЛО:
Ты работаешь ТОЛЬКО через объект `h` (FreeCADHelper). Никогда не используй голый FreeCAD API.

### ДОСТУПНЫЕ МЕТОДЫ h:

**Создание тел:**
- h.box(length, width, height, name) — параллелепипед
- h.cylinder(radius, height, name) — цилиндр
- h.sphere(radius, name) — сфера
- h.cone(radius1, radius2, height, name) — конус
- h.torus(radius1, radius2, name) — тор

**Boolean-операции:**
- h.fuse(obj1, obj2, name, remove_old=True) — объединение
- h.cut(base, tool, name, remove_old=True) — вычитание (объекты ДОЛЖНЫ пересекаться!)
- h.intersect(obj1, obj2, name) — пересечение
- h.through_hole(base, cx, cy, radius, name) — сквозное отверстие

**Модификация:**
- h.fillet(obj, radius, name) — скругление рёбер
- h.chamfer(obj, size, name) — фаска

**Позиционирование:**
- h.move(obj, x, y, z) — перемещение
- h.place(obj, x, y, z, rx, ry, rz) — размещение + поворот

**Информация:**
- h.list_objects() — список всех объектов в документе
- h.info(obj) — объём, площадь, габариты объекта
- h.clear() — удалить все объекты

**Экспорт:**
- h.export_stl(path) — экспорт в STL
- h.export_step(path) — экспорт в STEP

### ПРАВИЛА КОДА:
1. Все единицы — МИЛЛИМЕТРЫ
2. Объекты сохраняй в переменные: `base = h.box(...)`, `cyl = h.cylinder(...)`
3. После создания проверяй: `h.list_objects()` или `h.info(obj)`
4. Для boolean операций сначала позиционируй объекты через h.move()
5. Используй remove_old=True в h.cut/h.fuse чтобы удалить оригиналы
6. Не используй `App`, `Part`, `cadquery` — ТОЛЬКО h.*
7. Имена объектов: `Base_Plate`, `Mount_Bracket`, `Hole_Tool`

### ФОРМАТ ОТВЕТА:
Всегда отвечай ТОЛЬКО JSON:
```
{"action": "code", "description": "описание", "code": "код на Python"}
```

### ФОРМАТ КОДА (КРИТИЧЕСКИ ВАЖНО):
- Код в поле `code` — это ОДНА строка с переносами \n
- НЕ используй вложенные JSON в JSON
- Каждая новая строка кода = \n в JSON-строке
- Примеры правильного формата:
  - "code": "base = h.box(100, 80, 15)\nh.move(base, 50, 40, 0)\nprint(h.info(base))"
  - "code": "cyl = h.cylinder(20, 50)\nh.cut(base, cyl, \"Hole\")"
- НЕ оборачивай код в ```python``` внутри JSON
- НЕ добавляй лишние отступы в начало строк

Если не хватает данных — спроси:
```json
{"action": "clarify", "message": "Какие размеры?"}
```

Если задача сложная — план:
```json
{"action": "plan", "steps": ["шаг 1: описание", "шаг 2: описание"]}
```

### ПРИМЕРЫ:

Запрос: "Создай куб 50x50x50"
```json
{"action": "code", "description": "Создание куба 50x50x50", "code": "base = h.box(50, 50, 50, 'Cube_50')\nprint(h.info(base))"}
```

Запрос: "Вырежь отверстие в кубе"
```json
{"action": "code", "description": "Вырезание отверстия в кубе", "code": "base = h.box(100, 100, 20, 'Plate')\ntool = h.cylinder(15, 30, 'Hole_Tool')\nh.move(tool, 50, 50, -5)\nresult = h.cut(base, tool, 'Plate_With_Hole', remove_old=True)\nprint(h.info(result))"}
```

Запрос: "Создай деталь по чертежу" (с изображением)
Проанализируй чертёж, определи размеры и форму,然后 создай модель пошагово.
""" + get_prompt_addition() + "\n\n" + get_tools_description() + "\n\n" + get_skills_description()

# --- Polza API ---
def call_polza(messages, system_prompt=None, model=None, temperature=0.3, max_tokens=4096):
    body = {"model": model or POLZA_MODEL, "messages": [], "temperature": temperature, "max_tokens": max_tokens}
    if system_prompt:
        body["messages"].append({"role": "system", "content": system_prompt})
    for m in messages:
        body["messages"].append(m)
    # Increase max_tokens for vision/comparison tasks
    if model and ('vision' in str(messages).lower() or 'screenshot' in str(messages).lower() or 'compare' in str(messages).lower()):
        body["max_tokens"] = max(max_tokens, 8192)
    conn = http.client.HTTPSConnection(POLZA_HOST, POLZA_PORT, timeout=180)
    conn.request('POST', POLZA_PATH, json.dumps(body), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + POLZA_API_KEY})
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    result = json.loads(data)
    if 'choices' in result and len(result['choices']) > 0:
        return result['choices'][0]['message']['content']
    raise Exception('No response: ' + data[:500])

# --- FreeCAD RPC ---
def rpc_call(method, args=None):
    args = args or []
    body = '<?xml version="1.0"?><methodCall><methodName>' + method + '</methodName><params>'
    for a in args:
        e = str(a).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
        body += '<param><value><string>' + e + '</string></value></param>'
    body += '</params></methodCall>'
    bb = body.encode('utf-8')
    conn = http.client.HTTPConnection(FREECAD_RPC_HOST, FREECAD_RPC_PORT, timeout=30)
    conn.request('POST', '/', bb, {'Content-Type': 'text/xml; charset=utf-8', 'Content-Length': str(len(bb))})
    data = conn.getresponse().read().decode()
    conn.close()
    if '<fault>' in data:
        f = re.search(r'<string>(.*?)</string>', data, re.DOTALL)
        raise Exception(f.group(1) if f else 'RPC fault')
    sm = re.search(r'<struct>(.*?)</struct>', data, re.DOTALL)
    if sm:
        r = {}
        for mm in re.finditer(r'<member>(.*?)</member>', sm.group(1), re.DOTALL):
            n = re.search(r'<name>(.*?)</name>', mm.group(1))
            if n:
                nm = n.group(1).strip()
                vs = re.search(r'<value>\s*<string>(.*?)</string>\s*</value>', mm.group(1), re.DOTALL)
                vb = re.search(r'<value>\s*<boolean>(.*?)</boolean>\s*</value>', mm.group(1))
                if vs: r[nm] = vs.group(1)
                elif vb: r[nm] = vb.group(1) == '1'
                else:
                    va = re.search(r'<value>(.*?)</value>', mm.group(1), re.DOTALL)
                    if va: r[nm] = re.sub(r'<[^>]+>', '', va.group(1)).strip()
        return r
    v = re.search(r'<string>(.*?)</string>', data, re.DOTALL)
    return v.group(1) if v else data

def ensure_document():
    global wrapper_initialized
    try: rpc_call('ping')
    except: return False
    if not wrapper_initialized:
        try:
            rpc_call('execute_code', ['import FreeCAD; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("AIDoc")'])
            # Force fresh wrapper: delete old h, reload module, re-exec
            rpc_call('execute_code', [
                'import sys\n'
                'if "freecad_api" in sys.modules: del sys.modules["freecad_api"]\n'
                'sys.path.insert(0, "/opt/freecad/bridge")\n'
                'import importlib, freecad_api\n'
                'importlib.reload(freecad_api)\n'
                'from freecad_api import get_wrapper_code\n'
                'exec(get_wrapper_code())\n'
                'print("Wrapper reloaded:", hasattr(h, "through_hole"))'
            ])
            wrapper_initialized = True
            log.info("Wrapper initialized")
        except Exception as e:
            log.error(f"Wrapper init failed: {e}"); return False
    return True

def clean_code(code):
    """Clean generated code: fix indentation, remove markdown artifacts."""
    if not code:
        return code
    # Remove markdown code block markers
    code = code.strip()
    if code.startswith('```python'):
        code = code[9:]
    elif code.startswith('```'):
        code = code[3:]
    if code.endswith('```'):
        code = code[:-3]
    code = code.strip()
    # Fix common issues: tabs -> spaces
    code = code.replace('\t', '    ')
    # Remove trailing whitespace on each line
    lines = code.split('\n')
    lines = [l.rstrip() for l in lines]
    code = '\n'.join(lines)
    return code

def execute_code_with_logs(code, step=None):
    try:
        code = clean_code(code)
        result = rpc_call('execute_code', [code])
        output = result.get('message', '') if isinstance(result, dict) else str(result)
        fc_logs = get_context_for_model(after_execution=True, step_output=output)
        if step: step.output = output; step.completed_at = time.time()
        return output, fc_logs, None
    except Exception as e:
        fc_logs = get_context_for_model(after_execution=True, step_output=str(e))
        if step: step.error = str(e); step.status = "error"; step.completed_at = time.time()
        return None, fc_logs, str(e)

def capture_screenshot():
    if not ENABLE_SCREENSHOT: return None
    for attempt in range(3):
        try:
            code = 'import FreeCADGui, tempfile, os; path = os.path.join(tempfile.gettempdir(), "freecad_screenshot.png"); ad = FreeCADGui.ActiveDocument; av = ad.ActiveView if ad else None; av.saveImage(path, 800, 600, "PNG") if av else None; print(path if av else "NO_VIEW")'
            result = rpc_call('execute_code', [code])
            msg = result.get('message', '') if isinstance(result, dict) else str(result)
            for line in msg.split('\n'):
                line = line.strip()
                # Strip RPC output prefix (e.g. 'Output: /path' or 'SCREENSHOT_OK:/path')
                if line.startswith('Output: '):
                    line = line[len('Output: '):].strip()
                elif line.startswith('SCREENSHOT_OK:'):
                    line = line[len('SCREENSHOT_OK:'):].strip()
                if line.endswith('.png'):
                    import time; time.sleep(0.5)  # wait for file write
                    if os.path.exists(line): return line
            log.debug(f"Screenshot attempt {attempt+1}: no valid path in output: {msg[:200]}")
        except Exception as e:
            log.debug(f"Screenshot attempt {attempt+1} failed: {e}")
    return None

def screenshot_to_base64(path):
    try:
        with open(path, 'rb') as f:
            return 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')
    except: return None

def get_document_objects():
    try:
        code = 'import FreeCAD, json; doc = FreeCAD.activeDocument(); objs = [{"name": o.Name, "type": o.TypeId, "pos": str(o.Placement.Base) if hasattr(o, "Placement") else "N/A"} for o in doc.Objects] if doc else []; print(json.dumps(objs))'
        result = rpc_call('execute_code', [code])
        msg = result.get('message', '') if isinstance(result, dict) else str(result)
        m = re.search(r'\[.*\]', msg, re.DOTALL)
        if m: return json.loads(m.group(0))
    except: pass
    return []

def extract_json(text):
    m = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(0))
        except: pass
    cm = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if cm:
        try: return json.loads(cm.group(1))
        except: pass
    bs = text.find('{')
    if bs >= 0:
        d = 0
        for i in range(bs, len(text)):
            if text[i] == '{': d += 1
            elif text[i] == '}':
                d -= 1
                if d == 0:
                    try: return json.loads(text[bs:i+1])
                    except: break
    return None

# === ReAct Agent ===
def react_execute(task, user_message, model_id=None, image_data=None, progress_callback=None, vision_mode=False):
    """ReAct-агент с опциональным progress_callback для SSE."""
    def notify(event_type, data):
        if progress_callback:
            progress_callback(event_type, data)

    # Сохраняем чертёж если передан
    if image_data and not task.reference_image:
        task.reference_image = image_data
        log.info(f"Reference image saved for task {task.task_id}")

    notify("start", {"task_id": task.task_id, "message": user_message[:100]})
    # qwen3.5-only mode: always use Kimi for code generation and vision
    model_id = "qwen/qwen3.5-35b-a3b"
    model_profile = MODELS.get("kimi")
    log.info(f"Model: Kimi k2.7-code (qwen3.5-only mode)")

    doc_objects = get_document_objects()
    doc_ctx = "\n\nObjects:\n" + "\n".join(f"- {o['name']} ({o['type']})" for o in doc_objects) if doc_objects else ""
    logs_ctx = get_recent_activity(5)

    # Динамические промпты по типу задачи
    needs_bool, needs_arr, needs_mod = detect_task_features(user_message)
    task_prompts = get_task_prompts(task_type="drawing" if "чертеж" in user_message.lower() or bool(image_data) else "modeling",
                                     needs_boolean=needs_bool, needs_array=needs_arr, needs_modifiers=needs_mod)

    # Plan
    plan_sys = get_system_prompt_for_model(model_id, BASE_SYSTEM_PROMPT, doc_ctx) + f"\n\n{logs_ctx}\n\n{task_prompts}"
    plan_msgs = [{"role": "user", "content": user_message}]
    if image_data and model_profile and model_profile.supports_vision:
        # Log image format details
        prefix = image_data[:30] if len(image_data) > 30 else image_data
        suffix = image_data[-20:] if len(image_data) > 20 else ''
        log.info(f"Image format: prefix='{prefix}' suffix='{suffix}' len={len(image_data)}")
        plan_msgs[0]["content"] = [{"type": "text", "text": user_message + "\n\nRussian only."}, {"type": "image_url", "image_url": {"url": image_data}}]
        log.info(f"Vision request: sending image ({len(image_data)} chars) to {model_id}")
    else:
        log.info(f"Text-only request: image_data={'yes' if image_data else 'no'}, supports_vision={model_profile.supports_vision if model_profile else 'no profile'}")

    notify("planning", {"model": model_id})
    try: plan_resp = call_polza(plan_msgs, plan_sys, model=model_profile.model_id if model_profile else None)
    except Exception as e:
        notify("error", {"message": str(e)})
        return {"reply": f"Error: {e}", "type": "error"}

    plan_action = extract_json(plan_resp)

    if plan_action and plan_action.get('action') == 'code':
        return execute_single(task, plan_action, model_id, model_profile, plan_msgs, plan_resp, doc_ctx, progress_callback, vision_mode=vision_mode)
    if plan_action and plan_action.get('action') == 'plan':
        steps_desc = plan_action.get('steps', [])
        if steps_desc:
            task.plan = steps_desc
            for d in steps_desc: task.add_step(d)
            return execute_plan(task, model_id, model_profile, doc_ctx, progress_callback, vision_mode=vision_mode)
    return {"reply": plan_resp, "type": "text"}

def execute_plan(task, model_id, model_profile, doc_ctx, progress_callback=None, vision_mode=False):
    """Execute all plan steps sequentially with progress notifications.
    Each step: generate code → execute → check errors → auto-fix → next step.
    If auto-fix fails 3 times → ask human for help.
    """
    results = []
    MAX_STEP_RETRIES = 3

    for i, step in enumerate(task.steps):
        if step.status != "pending": continue
        step.status = "running"; step.started_at = time.time(); step.model_used = model_id
        if progress_callback:
            progress_callback("step_start", {"step": i+1, "total": len(task.steps), "description": step.description})

        step_ctx = task_manager.build_task_context(task)
        step_logs = get_recent_activity(3)

        # Rich context for each step
        current_objects = get_document_objects()
        objects_desc = "\n".join(f"- {o['name']} ({o['type']})" for o in current_objects) if current_objects else "(пусто)"

        step_sys = get_system_prompt_for_model(model_id, BASE_SYSTEM_PROMPT, doc_ctx + "\n\n" + step_ctx + "\n\n" + step_logs)
        step_msgs = [{"role": "user", "content": (
            f"ШАГ {i+1}/{len(task.steps)}: {step.description}\n\n"
            f"Текущие объекты в документе:\n{objects_desc}\n\n"
            f"Сгенерируй Python-код используя h.* wrapper.\n"
            f"После кода добавь h.list_objects() для проверки результата.\n"
            f"Ответ ТОЛЬКО JSON: {{\"action\": \"code\", \"description\": \"...\", \"code\": \"...\"}}")}]

        # Step execution with auto-correction loop
        step_ok = False
        for attempt in range(MAX_STEP_RETRIES):
            try:
                resp = call_polza(step_msgs, step_sys, model=model_profile.model_id if model_profile else None)
            except Exception as e:
                step.error = str(e)
                task.error_log.append(f"Step {i+1} API error (attempt {attempt+1}): {e}")
                if attempt < MAX_STEP_RETRIES - 1:
                    step_msgs.append({"role": "assistant", "content": resp})
                    step_msgs.append({"role": "user", "content": f"Ошибка API: {e}. Попробуй ещё раз."})
                    continue
                break

            action = extract_json(resp)
            if not action or action.get('action') != 'code':
                # Model didn't return code - retry with explicit instruction
                step_msgs.append({"role": "assistant", "content": resp})
                step_msgs.append({"role": "user", "content": (
                    "Ты должен вернуть ТОЛЬКО JSON с action=code. "
                    "Пример: {\"action\": \"code\", \"description\": \"...\", \"code\": \"h.box(...)\"}")})
                if attempt < MAX_STEP_RETRIES - 1:
                    continue
                step.status = "error"; step.error = "Model didn't return code"
                task.error_log.append(step.error)
                results.append({"step": i+1, "status": "error", "error": step.error})
                break

            code = action.get('code', '')
            step.code = code
            safe = code.encode('ascii', 'ignore').decode('ascii')

            # Execute code
            out, logs, err = execute_code_with_logs(safe, step)

            if not err:
                # Success!
                step.status = "success"
                step_ok = True
                output_summary = (out or "OK")[:500]
                results.append({"step": i+1, "status": "success", "output": output_summary})
                log.info(f"Step {i+1} OK: {step.description[:50]}")

                # Report success to model for next step context
                step_msgs.append({"role": "assistant", "content": resp})
                step_msgs.append({"role": "user", "content": f"Шаг выполнен успешно. Результат: {output_summary}"})
                break
            else:
                # Error - auto-correct
                step.retry_count += 1
                task.error_log.append(err)
                log.warning(f"Step {i+1} attempt {attempt+1}/{MAX_STEP_RETRIES} error: {err[:200]}")

                # Get Report view errors
                report_ctx = build_error_context_for_model(rpc_call, task.user_request)

                error_msg = (
                    f"ОШИБКА при выполнении шага {i+1}:\n"
                    f"{err}\n\n"
                    f"Исправь код и повтори. Используй ТОЛЬКО h.* wrapper.\n"
                    f"Ответ: {{\"action\": \"code\", \"description\": \"...\", \"code\": \"...\"}}")
                if report_ctx:
                    error_msg += f"\n\nДополнительная информация из FreeCAD:\n{report_ctx[:500]}"

                step_msgs.append({"role": "assistant", "content": resp})
                step_msgs.append({"role": "user", "content": error_msg})

        if not step_ok and step.status != "success":
            # All retries failed - ask human
            step.status = "error"
            task.status = "error"
            last_error = step.error or "Не удалось выполнить шаг"
            results.append({"step": i+1, "status": "error", "error": last_error})
            if progress_callback:
                progress_callback("ask_human", {
                    "step": i+1,
                    "error": last_error[:200],
                    "message": f"Не удалось автоматически исправить шаг {i+1}: {step.description}. Помогите с решением."
                })
            break

        # Visual check after each step
        if ENABLE_VISUAL_CHECK and step_ok:
            screenshots = capture_compare_views(rpc_call)
            if screenshots:
                step.screenshot_path = list(screenshots.values())[0]
                log.info(f"Step {i+1} visual check: {len(screenshots)} views captured")

    task.status = "completed" if not task.failed_steps() else "error"
    task.objects_snapshot = get_document_objects()

    parts = [f"Задача: {task.user_request[:100]}", f"Прогресс: {task.progress_pct()}% ({len(task.completed_steps())}/{len(task.steps)})"]
    for r in results:
        icon = "+" if r["status"] == "success" else "X"
        parts.append(f"[{icon}] Шаг {r['step']}: {r['status']}")
        if r.get("error"): parts.append(f"   Ошибка: {r['error'][:150]}")

    # Финальное сравнение с чертежом
    if task.reference_image and ENABLE_VISUAL_CHECK:
        final_result = final_blueprint_comparison(task, model_profile, progress_callback)
        if final_result:
            parts.append(f"\n🔍 Финальное сравнение: {final_result}")

    return {"reply": "\n".join(parts), "type": "multi_step", "task": task.to_dict(), "objects": task.objects_snapshot}

def final_blueprint_comparison(task, model_profile, progress_callback=None, vision_mode=False):
    """Финальное сравнение построенной модели с исходным чертежом.
    
    Цикл: 4 скриншота (Front/Top/Right/Iso) → сравнение → коррекция → повтор.
    Максимум 3 раунда коррекции.
    """
    if not task.reference_image or not model_profile or not model_profile.supports_vision:
        return None

    MAX_COMPARE_ROUNDS = 3
    fc_model = "qwen/qwen3.5-35b-a3b"

    for round_num in range(MAX_COMPARE_ROUNDS):
        task.comparison_rounds += 1
        log.info(f"Final comparison round {round_num + 1}/{MAX_COMPARE_ROUNDS} (model: {fc_model})")

        if progress_callback:
            progress_callback("visual_check", {"round": round_num + 1, "max": MAX_COMPARE_ROUNDS})

        # 4 скриншота с центрированием
        screenshots = capture_compare_views(rpc_call)
        if not screenshots or len(screenshots) < 3:
            log.warning(f"Final comparison: only {len(screenshots or {})} screenshots captured")
            # fallback: try single screenshot
            sp = capture_screenshot()
            if not sp:
                return "скриншот недоступен"
            screenshots = {"Iso": sp}

        b64_map = screenshots_to_base64(screenshots)
        if not b64_map:
            return "скриншот не удалось прочитать"

        # Сравнение через vision-модель (все 4 вида)
        compare_system = (
            "Ты — инженер-конструктор. Сравни построенную 3D-модель с исходным чертёжом."
            "\n\nТебе показаны 4 ракурса: Front (спереди), Top (сверху), Right (справа), Iso (изометрия)."
            "\n\nПроанализируй:"
            "\n1. Соответствует ли форма модели чертежу?"
            "\n2. Есть ли расхождения в размерах, пропорциях, отверстиях, пазах?"
            "\n3. Совпадают ли виды спереди, сверху, справа?"
            "\n4. Насколько точно модель повторяет чертёж?"
            "\n\nДоступные методы для коррекции (ОБЯЗАТЕЛЬНО используй эти методы):"
            "\n- h.box(dx, dy, dz, name) — коробка"
            "\n- h.cylinder(r, h, name) — цилиндр"
            "\n- h.fuse(obj1, obj2, name) — объединение"
            "\n- h.cut(base, tool, name) — вычитание (объекты ДОЛЖНЫ пересекаться!)"
            "\n- h.through_hole(base, cx, cy, radius) — сквозное отверстие"
            "\n- h.fillet(obj, r, name) — скругление"
            "\n- h.move(obj, x, y, z) — перемещение"
            "\n- h.place(obj, x, y, z, rx, ry, rz) — размещение"
            "\n- h.list_objects() — список объектов"
            "\n- h.clear() — очистка документа"
            "\n\nНЕ используй cadquery, Part, или сырой FreeCAD API!"
            "\n\nВАЖНО: При коррекции НЕ используй h.clear()! Не пересоздавай модель с нуля."
            "\nИсправляй ТОЛЬКО конкретные различия: добавь недостающие отверстия, измени размеры,"
            "\nсдвинь/поверни неправильные элементы. Сохраняй правильные части модели."
            "\n\nОтвет ТОЛЬКО JSON:" +
            '{"match": true/false, "accuracy": "high/medium/low", "differences": ["diff1"], "correction_code": "Python code using h.* wrapper ONLY" or null, "summary": "brief summary in Russian"}'
        )

        # Собираем все скриншоты + чертёж
        content = [{"type": "text", "text": f"Задача: {task.user_request}\n\nРаунд {round_num + 1}/{MAX_COMPARE_ROUNDS}. Сравни модель с чертежом по 4 ракурсам."}]
        for view_name, b64 in b64_map.items():
            content.append({"type": "text", "text": f"--- {view_name} view ---"})
            content.append({"type": "image_url", "image_url": {"url": b64}})
        content.append({"type": "text", "text": "--- Оригинальный чертёж ---"})
        content.append({"type": "image_url", "image_url": {"url": task.reference_image}})

        compare_msgs = [{"role": "user", "content": content}]

        try:
            vr = call_polza(compare_msgs, compare_system, model=fc_model)
            log.info(f"Final comparison response ({fc_model}): {vr[:400]}")
            va = extract_json(vr)
        except Exception as e:
            log.error(f"Final comparison API error: {e}")
            return f"ошибка API: {e}"

        if not va:
            return "модель не вернула структурированный ответ"

        is_match = va.get("match", True)
        accuracy = va.get("accuracy", "unknown")
        summary = va.get("summary", "")
        differences = va.get("differences", [])
        correction_code = va.get("correction_code")

        log.info(f"Final comparison: match={is_match}, accuracy={accuracy}, diffs={len(differences)}")

        if is_match:
            return f"✅ Совпадает (точность: {accuracy}). {summary}"

        # Есть расхождения — нужна коррекция
        if not correction_code:
            return f"❌ Расхождения без кода коррекции: {'; '.join(differences[:3])}"

        # Валидация: correction_code должен использовать h.* wrapper
        if 'cadquery' in correction_code.lower() or 'import Part' in correction_code:
            log.warning(f"Correction uses wrong API (cadquery/Part), skipping")
            return f"❌ Расхождения: {'; '.join(differences[:3])}. Vision-модель вернула код не на h.* wrapper."

        # Применяем коррекцию
        log.info(f"Applying correction round {round_num + 1}: {correction_code[:200]}")
        if progress_callback:
            progress_callback("step_start", {"step": 99, "total": 100, "description": f"Коррекция раунд {round_num + 1}: {summary[:80]}"})

        safe_code = correction_code.encode('ascii', 'ignore').decode('ascii')
        out, logs, err = execute_code_with_logs(safe_code)

        if err:
            log.warning(f"Correction failed: {err}")
            return f"❌ Расхождения: {'; '.join(differences[:3])}. Коррекция упала: {err[:200]}"

        log.info(f"Correction applied, rechecking...")
        if progress_callback:
            progress_callback("visual_check_done", {"round": round_num + 1, "match": False, "applied": True})

    # После всех раундов
    return f"⚠️ После {MAX_COMPARE_ROUNDS} раундов коррекции: {summary}"

def execute_single(task, action, model_id, model_profile, msgs, resp_text, doc_ctx, progress_callback=None, vision_mode=False):
    code = action.get('code', '')
    desc = action.get('description', '')
    safe = code.encode('ascii', 'ignore').decode('ascii')
    step = task.add_step(desc); step.status = "running"; step.started_at = time.time()
    step.code = code; step.model_used = model_id
    if progress_callback:
        progress_callback("step_start", {"step": 1, "total": 1, "description": desc})
    ensure_document()
    ok = False
    for attempt in range(MAX_RETRIES + 1):
        out, logs, err = execute_code_with_logs(safe, step)
        if not err: step.status = "success"; ok = True; break
        task.error_log.append(err); step.retry_count += 1
        if attempt < MAX_RETRIES:
            fb = task_manager.build_error_feedback(task, err, logs)
            msgs.extend([{"role": "assistant", "content": resp_text}, {"role": "user", "content": fb}])
            try:
                resp_text = call_polza(msgs, BASE_SYSTEM_PROMPT + "\n\n" + doc_ctx, model=model_profile.model_id if model_profile else None)
                na = extract_json(resp_text)
                if na and na.get('action') == 'code':
                    code = na.get('code', ''); step.code = code; safe = code.encode('ascii', 'ignore').decode('ascii')
            except: break
    if not ok:
        task.status = "error"; task.objects_snapshot = get_document_objects()
        return {"reply": f"Error after {MAX_RETRIES+1} attempts:\n{step.error[:500]}", "type": "error", "task": task.to_dict()}
    if ENABLE_VISUAL_CHECK:
        screenshots = capture_compare_views(rpc_call)
        if screenshots:
            step.screenshot_path = list(screenshots.values())[0]
    task.status = "completed"; task.objects_snapshot = get_document_objects()

    # Финальное сравнение с чертежом
    comparison_note = ""
    if task.reference_image and ENABLE_VISUAL_CHECK:
        comp = final_blueprint_comparison(task, model_profile, vision_mode=vision_mode)
        if comp: comparison_note = f"\n\n🔍 Финальное сравнение: {comp}"

    reply = f"Done: {desc}\n\n```python\n{code}\n```\n\nResult:\n```\n{out or 'OK'}\n```{comparison_note}"
    if step.retry_count > 0: reply += f"\n\nAuto-fixed x{step.retry_count}:\n```\n{logs[:300]}\n```"
    return {"reply": reply, "code": code, "output": out, "type": "code_execution", "task": task.to_dict(), "objects": task.objects_snapshot}

# === HTTP Server ===
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class ChatHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): log.info(fmt % args)
    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', CORS_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    def _body(self):
        cl = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(cl)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/status': self._handle_status()
        elif self.path.startswith('/api/task/'): self._handle_task_get()
        else: self.send_response(404); self.end_headers()

    def do_POST(self):
        routes = {
            '/api/chat': self._handle_chat,
            '/api/chat/stream': self._handle_chat_stream,
            '/api/status': self._handle_status,
            '/api/export': self._handle_export,
            '/api/execute': self._handle_execute,
            '/api/feedback': self._handle_feedback,
            '/api/task/clear': self._handle_task_clear,
            '/api/new': self._handle_new,
        }
        handler = routes.get(self.path)
        if handler: handler()
        else: self.send_response(404); self.end_headers()

    def _handle_status(self):
        try: rpc_call('ping'); rpc_ok = True
        except: rpc_ok = False
        self._json({"status": "ok" if rpc_ok else "degraded", "rpc": "connected" if rpc_ok else "disconnected",
                     "model": POLZA_MODEL, "wrapper": wrapper_initialized, "tasks": task_manager.stats(), "version": "2.0.0"})

    def _handle_task_get(self):
        tid = self.path.split('/')[-1]
        t = task_manager.get_task(tid)
        self._json(t.to_dict() if t else {"error": "not found"}, 200 if t else 404)

    def _handle_task_clear(self):
        with task_manager._lock: task_manager._tasks.clear()
        self._json({"ok": True})

    def _handle_new(self):
        global wrapper_initialized
        try:
            try:
                rpc_call('execute_code', [
                    'import FreeCAD\n'
                    'doc = FreeCAD.activeDocument()\n'
                    'if doc:\n'
                    '    for obj in doc.Objects[:]: doc.removeObject(obj.Name)\n'
                    '    doc.recompute()\n'
                    'else:\n'
                    '    doc = FreeCAD.newDocument("AIDoc")'
                ])
            except Exception as e:
                log.warning(f"Clear doc: {e}")
            wrapper_initialized = False
            ensure_document()
            with task_manager._lock: task_manager._tasks.clear()
            self._json({"ok": True, "message": "New document + tasks cleared"})
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)

    def _handle_chat(self):
        data = json.loads(self._body().decode())
        msg = data.get('message', '')
        model = data.get('model', None)
        img = data.get('image', None)
        vision_mode = data.get('vision_mode', False)
        tid = data.get('task_id', None)
        try:
            ensure_document()
            if tid:
                task = task_manager.get_task(tid)
                if not task: task = task_manager.create_task(msg)
            else:
                task = task_manager.get_or_create_recent(msg, max_age=300)
                if task.status not in ("active",): task = task_manager.create_task(msg)
            result = react_execute(task, msg, model_id=model, image_data=img, vision_mode=vision_mode)
            if "task" not in result: result["task"] = task.to_dict()
            result["task_id"] = task.task_id
            self._json(result)
        except Exception as e:
            traceback.print_exc()
            self._json({"reply": f"Error: {e}", "type": "error"})

    def _handle_chat_stream(self):
        """SSE endpoint — streaming progress for chat."""
        data = json.loads(self._body().decode())
        msg = data.get('message', '')
        model = data.get('model', None)
        img = data.get('image', None)
        tid = data.get('task_id', None)
        vision_mode = data.get('vision_mode', False)

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', CORS_ORIGIN)
        self.end_headers()

        def send_sse(event_type, event_data):
            try:
                payload = json.dumps(event_data, ensure_ascii=False)
                self.wfile.write(f"event: {event_type}\ndata: {payload}\n\n".encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

        try:
            ensure_document()
            if tid:
                task = task_manager.get_task(tid)
                if not task: task = task_manager.create_task(msg)
            else:
                task = task_manager.get_or_create_recent(msg, max_age=300)
                if task.status not in ("active",): task = task_manager.create_task(msg)

            send_sse("start", {"task_id": task.task_id})
            result = react_execute(task, msg, model_id=model, image_data=img, progress_callback=send_sse, vision_mode=vision_mode)
            if "task" not in result: result["task"] = task.to_dict()
            result["task_id"] = task.task_id
            send_sse("done", result)
        except Exception as e:
            traceback.print_exc()
            send_sse("error", {"reply": f"Error: {e}", "type": "error"})

    def _handle_export(self):
        data = json.loads(self._body().decode())
        fmt = data.get('format', 'stl').lower()
        fn = data.get('filename', 'freecad_export')
        if fmt not in ('stl', '3mf'): self._json({"error": "bad format"}, 400); return
        ext = fmt; ep = f'/tmp/{fn}.{ext}'
        try:
            ensure_document()
            ec = f'import FreeCAD, Mesh; doc = FreeCAD.activeDocument(); shapes = [o for o in doc.Objects if hasattr(o, "Shape")]; Mesh.export(shapes, "{ep}") if shapes else None; print("EXPORT_OK:{ep}" if shapes else "EXPORT_ERROR:No shapes")'
            r = rpc_call('execute_code', [ec])
            o = r.get('message', '') if isinstance(r, dict) else str(r)
            if 'EXPORT_OK:' in o:
                fp = o.split('EXPORT_OK:')[1].strip()
                with open(fp, 'rb') as f: fd = f.read()
                self._json({"status": "ok", "format": fmt, "filename": f"{fn}.{ext}", "size": len(fd), "data": base64.b64encode(fd).decode('ascii')})
            else: self._json({"status": "error", "message": o.strip()})
        except Exception as e: self._json({"error": str(e)}, 500)

    def _handle_execute(self):
        data = json.loads(self._body().decode())
        code = data.get('code', '')
        if not code.strip(): self._json({"error": "no code"}, 400); return
        try:
            ensure_document()
            r = rpc_call('execute_code', [code.encode('ascii', 'ignore').decode('ascii')])
            o = r.get('message', '') if isinstance(r, dict) else str(r)
            self._json({"status": "ok", "output": o, "code": code})
        except Exception as e: self._json({"error": str(e)}, 500)

    def _handle_feedback(self):
        data = json.loads(self._body().decode())
        ref = data.get('reference_image', '')
        desc = data.get('description', '')
        vision_mode = data.get('vision_mode', False)
        if not ref: self._json({"error": "no image"}, 400); return
        try:
            ensure_document()
            # 4 скриншота с центрированием
            screenshots = capture_compare_views(rpc_call)
            if not screenshots:
                self._json({"error": "screenshot failed"}, 500); return
            b64_map = screenshots_to_base64(screenshots)
            if not b64_map:
                self._json({"error": "screenshot encode failed"}, 500); return

            cs = (
                "Compare created model (4 views: Front/Top/Right/Iso) with reference drawing. "
                "Use h.* wrapper methods for corrections (h.box, h.cylinder, h.cut, h.fuse, h.move, h.through_hole). "
                "NEVER use cadquery or raw FreeCAD API. "
                "Reply JSON: " + '{"match": true/false, "differences": [...], "correction_code": "Python code using h.* ONLY" or null, "summary": "..."}'
            )

            # Собираем контент: 4 скриншота + чертёж
            content = [{"type": "text", "text": f"Compare with reference. Description: {desc}"}]
            for vn, b64 in b64_map.items():
                content.append({"type": "text", "text": f"--- {vn} view ---"})
                content.append({"type": "image_url", "image_url": {"url": b64}})
            content.append({"type": "text", "text": "--- Reference drawing ---"})
            content.append({"type": "image_url", "image_url": {"url": ref}})
            cm = [{"role": "user", "content": content}]

            # Kimi-only: always use Kimi
            feedback_model = "qwen/qwen3.5-35b-a3b"
            log.info(f"Feedback model: {feedback_model}")
            ai = call_polza(cm, cs, model=feedback_model)
            cmp = extract_json(ai) or {"match": False, "differences": [], "correction_code": None, "summary": ai[:200]}
            applied = False
            if cmp.get('correction_code') and not cmp.get('match', True):
                try:
                    correction_code = cmp['correction_code']
                    if 'cadquery' in correction_code.lower() or 'import Part' in correction_code:
                        log.warning(f"Correction uses wrong API, skipping: {correction_code[:100]}")
                    else:
                        rpc_call('execute_code', [correction_code.encode('ascii', 'ignore').decode('ascii')])
                        applied = True
                except Exception as e:
                    log.warning(f"Feedback correction failed: {e}")
            # Return first screenshot as main view
            main_sb64 = b64_map.get('Iso', list(b64_map.values())[0]) if b64_map else None
            self._json({"status": "ok", "screenshot": main_sb64, "comparison": cmp, "correction_applied": applied, "views": list(b64_map.keys())})
        except Exception as e: self._json({"error": str(e)}, 500)

def main():
    log.info(f"Bridge v2.0 starting on port {BRIDGE_PORT}")
    log.info(f"  Model: {POLZA_MODEL}")
    log.info(f"  RPC: {FREECAD_RPC_HOST}:{FREECAD_RPC_PORT}")
    log.info(f"  Visual check: {ENABLE_VISUAL_CHECK}")
    try: rpc_call('ping'); log.info("  RPC: connected")
    except: log.warning("  RPC: not available")
    server = ThreadedHTTPServer(('0.0.0.0', BRIDGE_PORT), ChatHandler)
    log.info(f"  Bridge: http://0.0.0.0:{BRIDGE_PORT}")
    def shutdown(s, f): log.info("Shutting down..."); threading.Thread(target=server.shutdown).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server.serve_forever()

if __name__ == '__main__': main()
