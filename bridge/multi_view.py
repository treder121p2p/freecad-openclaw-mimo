#!/usr/bin/env python3
"""
Multi-View Screenshots — скриншоты с разных ракурсов.
Основано на: neka-nat/freecad-mcp (get_view с named cameras)
"""

import os
import time
import base64
import logging

log = logging.getLogger("multi_view")

VIEW_ANGLES = {
    "Front":  "FreeCADGui.ActiveDocument.ActiveView.viewFront()",
    "Back":   "FreeCADGui.ActiveDocument.ActiveView.viewBack()",
    "Top":    "FreeCADGui.ActiveDocument.ActiveView.viewTop()",
    "Bottom": "FreeCADGui.ActiveDocument.ActiveView.viewBottom()",
    "Right":  "FreeCADGui.ActiveDocument.ActiveView.viewRight()",
    "Left":   "FreeCADGui.ActiveDocument.ActiveView.viewLeft()",
    "Iso":    "FreeCADGui.ActiveDocument.ActiveView.viewIsometric()",
    "Dimetric": "FreeCADGui.ActiveDocument.ActiveView.viewDimetric()",
    "Trimetric": "FreeCADGui.ActiveDocument.ActiveView.viewTrimetric()",
}

# 4 views for comparison: 3 orthographic + 1 isometric
COMPARE_VIEWS = ["Front", "Top", "Right", "Iso"]

# Minimum verification set (legacy)
VERIFY_VIEWS = ["Front", "Top", "Iso"]


def center_and_fit(rpc_call_fn):
    """Центрировать и вписать модель в вид (ViewFitAll)."""
    code = (
        "import FreeCADGui\n"
        "FreeCADGui.SendMsgToActiveView(\"ViewFitAll\")\n"
        "import time; time.sleep(0.5)\n"
        "print('CENTER_OK')"
    )
    try:
        result = rpc_call_fn('execute_code', [code])
        output = result.get('message', '') if isinstance(result, dict) else str(result)
        log.info(f"Center view: {output[:100]}")
        time.sleep(0.3)  # additional settle time
        return True
    except Exception as e:
        log.error(f"Center view failed: {e}")
        return False


def capture_view(rpc_call_fn, view_name="Iso", filename=None, center_first=True):
    """Сделать скриншот с конкретного ракурса."""
    if view_name not in VIEW_ANGLES:
        log.warning(f"Unknown view: {view_name}, using Iso")
        view_name = "Iso"

    if not filename:
        filename = f"view_{view_name.lower()}.png"

    code = (
        f"import FreeCADGui, tempfile, os, time\n"
        f"FreeCADGui.SendMsgToActiveView(\"ViewFitAll\")\n"
        f"time.sleep(0.5)\n"
        f"view_cmd = '{VIEW_ANGLES[view_name]}'\n"
        f"exec(view_cmd)\n"
        f"time.sleep(0.3)\n"
        f"path = os.path.join(tempfile.gettempdir(), '{filename}')\n"
        f"FreeCADGui.ActiveDocument.ActiveView.saveImage(path, 800, 600, 'PNG')\n"
        f"print('SCREENSHOT_OK:' + path)"
    )

    try:
        result = rpc_call_fn('execute_code', [code])
        output = result.get('message', '') if isinstance(result, dict) else str(result)

        for line in output.split('\n'):
            line = line.strip()
            # Strip RPC output prefix
            if line.startswith('Output: '):
                line = line[len('Output: '):].strip()
            if line.startswith('SCREENSHOT_OK:'):
                line = line[len('SCREENSHOT_OK:'):].strip()
            if line.endswith('.png'):
                time.sleep(0.3)
                if os.path.exists(line):
                    return line

        log.warning(f"Screenshot failed for view {view_name}: {output[:200]}")
    except Exception as e:
        log.error(f"Screenshot error: {e}")

    return None


def capture_compare_views(rpc_call_fn, views=None):
    """Сделать 4 скриншота для сравнения: Front, Top, Right, Iso.
    Каждый скриншот центрирует вид перед захватом.
    """
    if views is None:
        views = COMPARE_VIEWS  # ["Front", "Top", "Right", "Iso"]
    
    # First: center the view globally
    center_and_fit(rpc_call_fn)
    
    results = {}
    for view in views:
        path = capture_view(rpc_call_fn, view, center_first=False)
        if path:
            results[view] = path
        else:
            log.warning(f"Failed to capture {view}")
    
    return results


def capture_multi_view(rpc_call_fn, views=None):
    """Сделать скриншоты с нескольких ракурсов."""
    if views is None:
        views = VERIFY_VIEWS

    results = {}
    for view in views:
        path = capture_view(rpc_call_fn, view)
        if path:
            results[view] = path
        else:
            log.warning(f"Failed to capture {view}")

    return results


def screenshots_to_base64(screenshot_paths):
    """Конвертировать скриншоты в base64."""
    results = {}
    for view, path in screenshot_paths.items():
        try:
            with open(path, 'rb') as f:
                b64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')
                results[view] = b64
        except Exception as e:
            log.warning(f"Failed to read {path}: {e}")
    return results


def build_multi_view_comparison(screenshots_b64, user_request, step_desc=""):
    """Построить multi-view сравнение с чертежом."""
    content = [
        {"type": "text", "text": (
            f"## Multi-View Verification\n\n"
            f"**User request:** {user_request}\n"
            f"**Step:** {step_desc}\n\n"
            f"You are shown the 3D model from 3 angles: Front, Top, Isometric.\n"
            f"Compare with the user's request.\n"
            f"Reply JSON: {{\"match\": true/false, \"issues\": [...], "
            f"\"front_ok\": true/false, \"top_ok\": true/false, \"iso_ok\": true/false, "
            f"\"summary\": \"...\"}}"
        )}
    ]

    for view, b64 in screenshots_b64.items():
        content.append({
            "type": "image_url",
            "image_url": {"url": b64}
        })

    return content


def verify_step(rpc_call_fn, vision_model_fn, user_request, step_desc=""):
    """Полная верификация шага: скриншоты → vision → verdict."""
    # 1. Capture multi-view screenshots
    screenshots = capture_multi_view(rpc_call_fn, VERIFY_VIEWS)
    if not screenshots:
        return {"verified": False, "reason": "screenshots_failed"}

    # 2. Convert to base64
    b64_screenshots = screenshots_to_base64(screenshots)
    if not b64_screenshots:
        return {"verified": False, "reason": "base64_failed"}

    # 3. Send to vision model
    comparison_content = build_multi_view_comparison(
        b64_screenshots, user_request, step_desc
    )

    system_prompt = (
        "You are a FreeCAD quality inspector.\n"
        "You see the model from 3 angles: Front, Top, Isometric.\n"
        "Compare with the user's request.\n"
        "Check: shape matches, proportions correct, features present.\n"
        "Reply JSON only."
    )

    try:
        result = vision_model_fn(comparison_content, system_prompt)
        return {
            "verified": True,
            "result": result,
            "screenshots": list(screenshots.keys()),
        }
    except Exception as e:
        log.error(f"Vision model error: {e}")
        return {"verified": False, "reason": str(e)}
