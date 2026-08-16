FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Yekaterinburg \
    DISPLAY=:1 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    FREECAD_VERSION=1.1.3 \
    FREECAD_USER_HOME=/config

# Minimal deps: Xvfb, VNC, noVNC, wget, fuse + libs for FreeCAD AppImage
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    xvfb \
    x11vnc \
    fluxbox \
    xterm \
    dbus-x11 \
    novnc \
    websockify \
    net-tools \
    procps \
    wget \
    fuse \
    libglu1-mesa \
    libgomp1 \
    libxcb-cursor0 \
    libxcb-keysyms1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xinerama0 \
    libxcb-xinput0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    python3 \
    python3-pip \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/freecad /workspace /config /var/log/freecad

# Download FreeCAD 1.1.3 AppImage from GitHub releases (x86_64, py3.11)
RUN wget -q -O /opt/freecad/FreeCAD.AppImage \
    "https://github.com/FreeCAD/FreeCAD/releases/download/${FREECAD_VERSION}/FreeCAD_${FREECAD_VERSION}-Linux-x86_64-py311.AppImage" \
    && chmod +x /opt/freecad/FreeCAD.AppImage

# FreeCADMCP addon
# FreeCAD 1.1.3 AppImage with HOME=/config uses UserAppDataDir=/config/
# So Mod dir is /config/Mod/ and settings go to /config/freecad_mcp_settings.json
COPY FreeCADMCP /config/Mod/FreeCADMCP
COPY freecad_mcp_settings.json /config/freecad_mcp_settings.json

# Web UI (VNC viewer + chat panel)
COPY webui/ /opt/freecad/webui/

# AI Bridge (MiMo ↔ FreeCAD RPC)
COPY bridge/ /opt/freecad/bridge/

COPY start-freecad.sh /opt/freecad/start-freecad.sh
COPY startup_rpc.py /opt/freecad/startup_rpc.py
RUN chmod +x /opt/freecad/start-freecad.sh

WORKDIR /workspace

EXPOSE 5900 6080 9875 9876 9877

CMD ["/opt/freecad/start-freecad.sh"]
