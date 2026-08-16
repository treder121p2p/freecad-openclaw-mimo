#!/usr/bin/env python3
"""
FreeCAD AI Bridge — MiMo + FreeCAD RPC
Receives user messages, calls MiMo via Polza API with FreeCAD system prompt,
extracts Python code, executes via RPC, returns results.
"""

import json
import os
import sys
import http.client
import urllib.parse
import re
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- Config ---
POLZA_HOST = os.environ.get("POLZA_HOST", "api.polza.ai")
POLZA_PORT = int(os.environ.get("POLZA_PORT", "443"))
POLZA_API_KEY = os.environ.get("POLZA_API_KEY", "")
POLZA_MODEL = os.environ.get("POLZA_MODEL", "xiaomi/mimo-v2.5")
POLZA_PATH = os.environ.get("POLZA_PATH", "/api/v1/chat/completions")
FREECAD_RPC_HOST = os.environ.get("FREECAD_RPC_HOST", "localhost")
FREECAD_RPC_PORT = int(os.environ.get("FREECAD_RPC_PORT", "9875"))
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "9877"))

# --- FreeCAD System Prompt ---
FREECAD_SYSTEM_PROMPT = """You are FreeCAD AI Assistant. You generate FreeCAD Python code from natural language.

## RULES:
1. ALWAYS create or get a document first: `doc = FreeCAD.activeDocument() or FreeCAD.newDocument("MyDoc")`
2. Always think step by step before generating code.
3. If the request is vague — ask clarifying questions FIRST (dimensions, position, etc.)
4. When generating code, output ONLY a JSON response with this structure:
   {"action": "code", "description": "Brief description", "code": "Python code here"}
5. If you need to ask a question, output:
   {"action": "clarify", "message": "Your question to the user"}
6. If the user asks to list/show objects, output:
   {"action": "code", "description": "List objects", "code": "doc = FreeCAD.activeDocument() or FreeCAD.newDocument(\"temp\"); print(\"\\n\".join([f\"{o.Name} ({o.TypeId})\" for o in doc.Objects]) if doc.Objects else \"Empty document\")"}
7. NEVER use import statements for FreeCAD modules unless needed (FreeCAD, Part, PartGui are pre-imported in execution context).
8. Always call doc.recompute() after creating/modifying objects.

## FreeCAD Python API Reference:

### Creating documents:
```python
doc = FreeCAD.newDocument("MyDoc")
```

### Getting active document:
```python
doc = FreeCAD.activeDocument()
```

### Primitive shapes (Part module):
```python
# Box
box = doc.addObject("Part::Box", "MyBox")
box.Length = 10.0  # mm
box.Width = 5.0
box.Height = 3.0
box.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(0, 0, 0))

# Cylinder
cyl = doc.addObject("Part::Cylinder", "MyCylinder")
cyl.Radius = 5.0
cyl.Height = 20.0
cyl.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(0, 0, 0))

# Sphere
sphere = doc.addObject("Part::Sphere", "MySphere")
sphere.Radius = 10.0

# Cone
cone = doc.addObject("Part::Cone", "MyCone")
cone.Radius1 = 5.0
cone.Radius2 = 0.0
cone.Height = 15.0

# Torus
torus = doc.addObject("Part::Torus", "MyTorus")
torus.Radius1 = 10.0  # major radius
torus.Radius2 = 3.0   # minor radius

# Wedge
wedge = doc.addObject("Part::Wedge", "MyWedge")

# Prism (regular polygon extrusion)
prism = doc.addObject("Part::Prism", "MyPrism")

# Pyramid
pyramid = doc.addObject("Part::Pyramid", "MyPyramid")
```

### Placement (position + rotation):
```python
import FreeCAD
# Position
obj.Placement.Base = FreeCAD.Vector(x, y, z)  # mm
# Rotation (Euler angles in degrees)
obj.Placement.Rotation = FreeCAD.Rotation(rx, ry, rz)
# Combined
obj.Placement = FreeCAD.Placement(FreeCAD.Vector(x, y, z), FreeCAD.Rotation(rx, ry, rz))
```

### Boolean operations:
```python
# Union (fuse)
result = shape1.fuse(shape2)
# Difference (cut)
result = shape1.cut(shape2)
# Intersection
result = shape1.intersect(shape2)

# Or using document objects:
bool_obj = doc.addObject("Part::Boolean", "MyBoolean")
bool_obj.Base = box
bool_obj.Tool = cylinder
bool_obj.Operation = "Fuse"  # or "Cut", "Common"
```

### Sketch-based objects:
```python
import Sketcher
sketch = doc.addObject("Sketcher::SketchObject", "MySketch")
sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(0,0,0), FreeCAD.Vector(10,0,0)))
sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(10,0,0), FreeCAD.Vector(10,10,0)))
sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(10,10,0), FreeCAD.Vector(0,10,0)))
sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(0,10,0), FreeCAD.Vector(0,0,0)))

# Pad (extrude)
pad = doc.addObject("PartDesign::Pad", "MyPad")
pad.Profile = sketch
pad.Length = 5.0
```

### Fillets and chamfers:
```python
# Fillet (rounded edges)
fillet = doc.addObject("Part::Fillet", "MyFillet")
fillet.Base = box
fillet.Edges = [(0, 2.0, 2.0)]  # (edge_index, radius1, radius2)

# Chamfer
chamfer = doc.addObject("Part::Chamfer", "MyChamfer")
chamfer.Base = box
```

### Section/analysis:
```python
# Get bounding box
bb = obj.Shape.BoundBox
print(f"X: {bb.XMin} to {bb.XMax}")
print(f"Y: {bb.YMin} to {bb.YMax}")
print(f"Z: {bb.ZMin} to {bb.ZMax}")

# Volume
print(f"Volume: {obj.Shape.Volume} mm³")

# Area
print(f"Surface area: {obj.Shape.Area} mm²")
```

### Common patterns:
```python
# Move object
obj.Placement.Base = FreeCAD.Vector(x, y, z)

# Copy object
new_obj = doc.addObject("Part::Feature", "Copy")
new_obj.Shape = obj.Shape.copy()

# Delete object
doc.removeObject("ObjectName")

# List all objects
for o in doc.Objects:
    print(f"{o.Name}: {o.TypeId}")

# Export to STL
Import.export(doc.Objects, "/tmp/model.stl")

# Export to STEP
Import.export(doc.Objects, "/tmp/model.step")

# View fit all
FreeCADGui.SendMsgToActiveView("ViewFit")
```

## IMPORTANT:
- Units are always in MILLIMETERS
- After any modification, call doc.recompute()
- Use descriptive object names (e.g., "Base_Plate", "Mount_Bracket")
- If the user says "create a shape" without dimensions, ASK for dimensions first
- If the user says "modify X", first check what X is, then modify
- Always confirm what you're about to do before executing complex operations
- Use ONLY ASCII characters in code (English comments only)
- Use descriptive object names like "Base_Plate", "Mount_Bracket"
- If the user says "create a shape" without dimensions, ASK for dimensions first
- If the user says "modify X", first check what X is, then modify
- Always confirm what you're about to do before executing complex operations
"""


def rpc_call(method, args=None):
    """Call FreeCAD RPC server."""
    args = args or []
    body = '<?xml version="1.0" encoding="UTF-8"?><methodCall><methodName>' + method + '</methodName><params>'
    for a in args:
        escaped = str(a).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        body += '<param><value><string>' + escaped + '</string></value></param>'
    body += '</params></methodCall>'

    body_bytes = body.encode('utf-8')
    conn = http.client.HTTPConnection(FREECAD_RPC_HOST, FREECAD_RPC_PORT, timeout=30)
    conn.request('POST', '/', body_bytes, {'Content-Type': 'text/xml; charset=utf-8', 'Content-Length': str(len(body_bytes))})
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()

    # Parse response
    if '<fault>' in data:
        fault = re.search(r'<string>(.*?)</string>', data, re.DOTALL)
        raise Exception(fault.group(1) if fault else 'RPC fault')

    # Try struct
    struct_match = re.search(r'<struct>(.*?)</struct>', data, re.DOTALL)
    if struct_match:
        result = {}
        for member in re.finditer(r'<member>(.*?)</member>', struct_match.group(1), re.DOTALL):
            name = re.search(r'<name>(.*?)</name>', member.group(1))
            if name:
                n = name.group(1).strip()
                val_str = re.search(r'<value>\s*<string>(.*?)</string>\s*</value>', member.group(1), re.DOTALL)
                val_bool = re.search(r'<value>\s*<boolean>(.*?)</boolean>\s*</value>', member.group(1))
                if val_str:
                    result[n] = val_str.group(1)
                elif val_bool:
                    result[n] = val_bool.group(1) == '1'
                else:
                    val_any = re.search(r'<value>(.*?)</value>', member.group(1), re.DOTALL)
                    if val_any:
                        result[n] = re.sub(r'<[^>]+>', '', val_any.group(1)).strip()
        return result

    # Simple value
    val = re.search(r'<string>(.*?)</string>', data, re.DOTALL)
    if val:
        return val.group(1)
    return data


def call_mimo(messages, system_prompt=None):
    """Call MiMo via Polza API (OpenAI-compatible)."""
    body = {
        "model": POLZA_MODEL,
        "messages": [],
        "temperature": 0.3,
        "max_tokens": 4096
    }

    if system_prompt:
        body["messages"].append({"role": "system", "content": system_prompt})

    for m in messages:
        body["messages"].append(m)

    body_json = json.dumps(body)

    conn = http.client.HTTPSConnection(POLZA_HOST, POLZA_PORT, timeout=120)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + POLZA_API_KEY
    }
    conn.request('POST', POLZA_PATH, body_json, headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()

    result = json.loads(data)
    if 'choices' in result and len(result['choices']) > 0:
        return result['choices'][0]['message']['content']
    raise Exception('No response from MiMo: ' + data[:500])


def get_document_context():
    """Get current FreeCAD document state for context."""
    try:
        result = rpc_call('execute_code', [
            'import FreeCAD; doc = FreeCAD.activeDocument(); '
            'objs = [{"name": o.Name, "type": o.TypeId, '
            '"pos": str(o.Placement.Base) if hasattr(o, "Placement") else "N/A"} '
            'for o in doc.Objects] if doc else []; '
            'import json; print(json.dumps(objs))'
        ])
        msg = result.get('message', '') if isinstance(result, dict) else str(result)
        # Extract JSON from output
        json_match = re.search(r'\[.*\]', msg, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        print(f"Context error: {e}")
    return []


def extract_json_from_response(text):
    """Extract JSON action from MiMo response."""
    # Try to find JSON block
    json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except:
            pass

    # Try code block
    code_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except:
            pass

    # Try to find any JSON-like structure with action
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('{') and '"action"' in line:
            try:
                return json.loads(line)
            except:
                pass

    return None


class ChatHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/chat':
            self.handle_chat()
        elif self.path == '/api/status':
            self.handle_status()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_status(self):
        try:
            rpc_call('ping')
            result = {"status": "ok", "rpc": "connected", "model": POLZA_MODEL}
        except:
            result = {"status": "error", "rpc": "disconnected"}

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def handle_chat(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode())

        user_message = data.get('message', '')
        history = data.get('history', [])

        try:
            # Get document context
            doc_context = get_document_context()
            context_str = ""
            if doc_context:
                context_str = "\n\nCurrent document objects:\n" + "\n".join(
                    [f"- {o['name']} ({o['type']}) at {o['pos']}" for o in doc_context]
                )

            # Build messages for MiMo
            system = FREECAD_SYSTEM_PROMPT + context_str
            messages = []
            # Add conversation history (last 10 messages)
            for h in history[-10:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
            messages.append({"role": "user", "content": user_message})

            # Call MiMo
            ai_response = call_mimo(messages, system)

            # Try to extract structured action
            action = extract_json_from_response(ai_response)

            if action and action.get('action') == 'code':
                code = action.get('code', '')
                desc = action.get('description', '')

                # Strip non-ASCII from code to avoid XML-RPC encoding issues
                safe_code = code.encode('ascii', 'ignore').decode('ascii')

                # Ensure document exists before executing
                ensure_doc_code = 'import FreeCAD; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("AIDoc")'
                try:
                    rpc_call('execute_code', [ensure_doc_code])
                except:
                    pass

                # Execute code in FreeCAD
                try:
                    rpc_result = rpc_call('execute_code', [safe_code])
                    output = rpc_result.get('message', '') if isinstance(rpc_result, dict) else str(rpc_result)

                    # Get updated context
                    new_context = get_document_context()

                    reply_text = "\u2705 " + desc + "\n\n```python\n" + code + "\n```\n\n**Result:**\n```\n" + output + "\n```"
                    result = {
                        "reply": reply_text,
                        "code": code,
                        "output": output,
                        "objects": new_context,
                        "type": "code_execution"
                    }
                except Exception as e:
                    err_text = "\u274c Error:\n```python\n" + code + "\n```\n\n**Error:** " + str(e)
                    result = {
                        "reply": err_text,
                        "code": code,
                        "error": str(e),
                        "type": "error"
                    }

            elif action and action.get('action') == 'clarify':
                result = {
                    "reply": action.get('message', ai_response),
                    "type": "clarify"
                }
            else:
                # No structured action — return raw AI response
                result = {
                    "reply": ai_response,
                    "type": "text"
                }

        except Exception as e:
            traceback.print_exc()
            result = {
                "reply": "\u274c " + str(e),
                "type": "error"
            }

        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


def main():
    print(f"FreeCAD AI Bridge starting on port {BRIDGE_PORT}")
    print(f"  Model: {POLZA_MODEL}")
    print(f"  FreeCAD RPC: {FREECAD_RPC_HOST}:{FREECAD_RPC_PORT}")

    # Test RPC connection
    try:
        rpc_call('ping')
        print("  RPC: connected ✓")
    except:
        print("  RPC: not available (will retry)")

    server = HTTPServer(('0.0.0.0', BRIDGE_PORT), ChatHandler)
    print(f"  Bridge: http://0.0.0.0:{BRIDGE_PORT}")
    server.serve_forever()


if __name__ == '__main__':
    main()
