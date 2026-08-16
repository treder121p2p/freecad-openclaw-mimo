#!/usr/bin/env bash
# Override: use separate Polza API key for FreeCAD bridge
export POLZA_API_KEY="pza_Gyz9IHREAgQrGddhPrm98lLDO4UHKOaX"
export POLZA_MODEL="xiaomi/mimo-v2.5"
exec python3 /opt/freecad/bridge/ai_bridge.py
