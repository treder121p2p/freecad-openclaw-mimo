#!/usr/bin/env bash
# FreeCAD AI Bridge v2.0 — uses .polza_key from /opt/freecad/.polza_key
# Available models: mimo-v2.5, mimo-v2.5-pro, claude-sonnet-4.6, qwen2.5-vl-72b
export POLZA_MODEL="xiaomi/mimo-v2.5"
export ENABLE_SCREENSHOT=1
export ENABLE_VISUAL_CHECK=1
export MAX_RETRIES=2
export MAX_REACT_STEPS=8
exec python3 /opt/freecad/bridge/ai_bridge.py
