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
from prompts import get_task_prompts, detect_task_features, VISUAL_CHECK_PROMPT

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
BASE_SYSTEM_PROMPT = """You are FreeCAD AI Assistant v2.0.

## RULES:
1. ALWAYS use the FreeCADHelper wrapper (object `h`) - NEVER use raw FreeCAD API
2. Wrapper methods: h.box(), h.cylinder(), h.sphere(), h.cone(), h.torus()
3. Booleans: h.fuse(), h.cut(), h.intersect()
4. Modifiers: h.fillet(), h.chamfer()
5. Movement: h.move(), h.rotate(), h.place()
6. Info: h.info(), h.list_objects(), h.clear()
7. Export: h.export_stl(), h.export_step()
8. All units in MILLIMETERS
9. After creation ALWAYS check: h.list_objects() or h.info(obj)
10. Output ONLY JSON: {"action": "code", "description": "...", "code": "..."}
11. Clarify: {"action": "clarify", "message": "..."}
12. Plan: {"action": "plan", "steps": ["step1", ...]}
13. Use descriptive names: "Base_Plate", "Mount_Bracket"
14. If dimensions not given - ask first
15. NEVER put for/while on same line with semicolons
""" + get_prompt_addition()

# --- Polza API ---
def call_polza(messages, system_prompt=None, model=None, temperature=0.3, max_tokens=4096):
    body = {"model": model or POLZA_MODEL, "messages": [], "temperature": temperature, "max_tokens": max_tokens}
    if system_prompt:
        body["messages"].append({"role": "system", "content": system_prompt})
    for m in messages:
        body["messages"].append(m)
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
            rpc_call('execute_code', [get_wrapper_code()])
            wrapper_initialized = True
            log.info("Wrapper initialized")
        except Exception as e:
            log.error(f"Wrapper init failed: {e}"); return False
    return True

def execute_code_with_logs(code, step=None):
    try:
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
    try:
        code = 'import FreeCADGui, tempfile, os; path = os.path.join(tempfile.gettempdir(), "freecad_screenshot.png"); FreeCADGui.ActiveDocument.ActiveView.saveImage(path, 800, 600, "PNG"); print(path)'
        result = rpc_call('execute_code', [code])
        msg = result.get('message', '') if isinstance(result, dict) else str(result)
        for line in msg.split('\n'):
            line = line.strip()
            if line.endswith('.png') and os.path.exists(line): return line
    except Exception as e:
        log.debug(f"Screenshot failed: {e}")
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
def react_execute(task, user_message, model_id=None, image_data=None, progress_callback=None):
    """ReAct-агент с опциональным progress_callback для SSE."""
    def notify(event_type, data):
        if progress_callback:
            progress_callback(event_type, data)

    notify("start", {"task_id": task.task_id, "message": user_message[:100]})
    if not model_id:
        model_id, model_profile, reason = select_model(user_message, has_image=bool(image_data))
        log.info(f"Model: {model_id} ({reason})")
    else:
        model_profile = None
        for k, v in MODELS.items():
            if v.model_id == model_id: model_profile = v; break

    doc_objects = get_document_objects()
    doc_ctx = "\n\nObjects:\n" + "\n".join(f"- {o['name']} ({o['type']})" for o in doc_objects) if doc_objects else ""
    logs_ctx = get_recent_activity(5)

    # Динамические промпты по типу задачи
    needs_bool, needs_arr, needs_mod = detect_task_features(user_message)
    task_prompts = get_task_prompts(task_type="drawing" if "чертеж" in user_message.lower() or has_image else "modeling",
                                     needs_boolean=needs_bool, needs_array=needs_arr, needs_modifiers=needs_mod)

    # Plan
    plan_sys = get_system_prompt_for_model(model_id, BASE_SYSTEM_PROMPT, doc_ctx) + f"\n\n{logs_ctx}\n\n{task_prompts}"
    plan_msgs = [{"role": "user", "content": user_message}]
    if image_data and model_profile and model_profile.supports_vision:
        plan_msgs[0]["content"] = [{"type": "text", "text": user_message + "\n\nRussian only."}, {"type": "image_url", "image_url": {"url": image_data}}]

    notify("planning", {"model": model_id})
    try: plan_resp = call_polza(plan_msgs, plan_sys, model=model_profile.model_id if model_profile else None)
    except Exception as e:
        notify("error", {"message": str(e)})
        return {"reply": f"Error: {e}", "type": "error"}

    plan_action = extract_json(plan_resp)

    if plan_action and plan_action.get('action') == 'code':
        return execute_single(task, plan_action, model_id, model_profile, plan_msgs, plan_resp, doc_ctx, progress_callback)
    if plan_action and plan_action.get('action') == 'plan':
        steps_desc = plan_action.get('steps', [])
        if steps_desc:
            task.plan = steps_desc
            for d in steps_desc: task.add_step(d)
            return execute_plan(task, model_id, model_profile, doc_ctx, progress_callback)
    return {"reply": plan_resp, "type": "text"}

def execute_plan(task, model_id, model_profile, doc_ctx, progress_callback=None):
    """Execute all plan steps sequentially with progress notifications."""
    results = []
    for i, step in enumerate(task.steps):
        if step.status != "pending": continue
        step.status = "running"; step.started_at = time.time(); step.model_used = model_id
        if progress_callback:
            progress_callback("step_start", {"step": i+1, "total": len(task.steps), "description": step.description})
        step_ctx = task_manager.build_task_context(task)
        step_logs = get_recent_activity(3)
        step_sys = get_system_prompt_for_model(model_id, BASE_SYSTEM_PROMPT, doc_ctx + "\n\n" + step_ctx + "\n\n" + step_logs)
        step_msgs = [{"role": "user", "content": f"Step {i+1}: {step.description}\nUse h.list_objects() first."}]

        try: resp = call_polza(step_msgs, step_sys, model=model_profile.model_id if model_profile else None)
        except Exception as e:
            step.status = "error"; step.error = str(e); step.completed_at = time.time()
            task.error_log.append(f"Step {i+1} API error: {e}")
            results.append({"step": i+1, "status": "error", "error": str(e)}); continue

        action = extract_json(resp)
        if action and action.get('action') == 'code':
            code = action.get('code', '')
            step.code = code
            safe = code.encode('ascii', 'ignore').decode('ascii')
            ok = False
            for attempt in range(MAX_RETRIES + 1):
                out, logs, err = execute_code_with_logs(safe, step)
                if not err: step.status = "success"; ok = True; results.append({"step": i+1, "status": "success", "output": (out or "")[:500]}); break
                step.retry_count += 1; task.error_log.append(err)
                if attempt < MAX_RETRIES:
                    fb = task_manager.build_error_feedback(task, err, logs)
                    step_msgs.extend([{"role": "assistant", "content": resp}, {"role": "user", "content": fb}])
                    try:
                        resp = call_polza(step_msgs, step_sys, model=model_profile.model_id if model_profile else None)
                        action = extract_json(resp)
                        if action and action.get('action') == 'code':
                            code = action.get('code', ''); step.code = code; safe = code.encode('ascii', 'ignore').decode('ascii')
                    except: break
            if not ok:
                step.status = "error"; task.status = "error"
                results.append({"step": i+1, "status": "error", "error": step.error}); break

            # Visual check (from article: 65% of code blocks trigger visual inspection)
            if ENABLE_VISUAL_CHECK and ok:
                sp = capture_screenshot()
                if sp:
                    step.screenshot_path = sp
                    b64 = screenshot_to_base64(sp)
                    if b64 and model_profile and model_profile.supports_vision:
                        try:
                            vs = "You are an engineer. Check the FreeCAD model on the screenshot against the task description. Reply JSON: " + '{"match": true/false, "issues": ["issue1"], "summary": "..."}'
                            vm = [{"role": "user", "content": [{"type": "text", "text": f"Task: {task.user_request}\nStep: {step.description}"}, {"type": "image_url", "image_url": {"url": b64}}]}]
                            vr = call_polza(vm, vs, model="anthropic/claude-sonnet-4.6")
                            va = extract_json(vr)
                            if va:
                                step.visual_match = va.get("match")
                                if not va.get("match", True):
                                    issues = va.get("issues", [])
                                    fix_fb = "Visual check failed:\n" + "\n".join(f"- {x}" for x in issues) + "\nFix step code."
                                    step_msgs.append({"role": "user", "content": fix_fb})
                                    try:
                                        fr = call_polza(step_msgs, step_sys, model="anthropic/claude-sonnet-4.6")
                                        fa = extract_json(fr)
                                        if fa and fa.get('action') == 'code':
                                            fc = fa.get('code', '').encode('ascii', 'ignore').decode('ascii')
                                            fo, fl, fe = execute_code_with_logs(fc, step)
                                            if not fe: step.status = "success"; step.visual_match = True
                                    except: pass
                        except Exception as e: log.debug(f"Visual check error: {e}")
        else:
            step.status = "skipped"; results.append({"step": i+1, "status": "skipped"})

    task.status = "error" if task.failed_steps() else "completed"
    task.objects_snapshot = get_document_objects()

    parts = [f"Task: {task.user_request[:100]}", f"Progress: {task.progress_pct()}% ({len(task.completed_steps())}/{len(task.steps)})"]
    for r in results:
        icon = "+" if r["status"] == "success" else "X" if r["status"] == "error" else "-"
        parts.append(f"[{icon}] Step {r['step']}: {r['status']}")
        if r.get("error"): parts.append(f"   Error: {r['error'][:150]}")

    return {"reply": "\n".join(parts), "type": "multi_step", "task": task.to_dict(), "objects": task.objects_snapshot}

def execute_single(task, action, model_id, model_profile, msgs, resp_text, doc_ctx, progress_callback=None):
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
        sp = capture_screenshot()
        if sp: step.screenshot_path = sp
    task.status = "completed"; task.objects_snapshot = get_document_objects()
    reply = f"Done: {desc}\n\n```python\n{code}\n```\n\nResult:\n```\n{out or 'OK'}\n```"
    if step.retry_count > 0: reply += f"\n\nAuto-fixed x{step.retry_count}:\n```\n{logs[:300]}\n```"
    return {"reply": reply, "code": code, "output": out, "type": "code_execution", "task": task.to_dict(), "objects": task.objects_snapshot}

# === HTTP Server ===
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer): daemon_threads = True

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

    def _handle_chat(self):
        data = json.loads(self._body().decode())
        msg = data.get('message', '')
        model = data.get('model', None)
        img = data.get('image', None)
        tid = data.get('task_id', None)
        try:
            ensure_document()
            if tid:
                task = task_manager.get_task(tid)
                if not task: task = task_manager.create_task(msg)
            else:
                task = task_manager.get_or_create_recent(msg, max_age=300)
                if task.status not in ("active",): task = task_manager.create_task(msg)
            result = react_execute(task, msg, model_id=model, image_data=img)
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
            result = react_execute(task, msg, model_id=model, image_data=img, progress_callback=send_sse)
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
        if not ref: self._json({"error": "no image"}, 400); return
        try:
            ensure_document()
            sp = capture_screenshot()
            if not sp: self._json({"error": "screenshot failed"}, 500); return
            with open(sp, 'rb') as f: sb64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')
            cs = "Compare created model (screenshot) with reference. Reply JSON: " + '{"match": true/false, "differences": [...], "correction_code": "python" or null, "summary": "..."}'
            cm = [{"role": "user", "content": [{"type": "text", "text": f"Compare with reference. Description: {desc}"}, {"type": "image_url", "image_url": {"url": sb64}}, {"type": "image_url", "image_url": {"url": ref}}]}]
            ai = call_polza(cm, cs, model="qwen/qwen2.5-vl-72b-instruct")
            cmp = extract_json(ai) or {"match": False, "differences": [], "correction_code": None, "summary": ai[:200]}
            applied = False
            if cmp.get('correction_code') and not cmp.get('match', True):
                try: rpc_call('execute_code', [cmp['correction_code'].encode('ascii', 'ignore').decode('ascii')]); applied = True
                except: pass
            self._json({"status": "ok", "screenshot": sb64, "comparison": cmp, "correction_applied": applied})
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
