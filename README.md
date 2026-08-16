# FreeCAD + OpenClaw + MiMo

3D-моделирование в Docker с AI-управлением через чат.

## Архитектура

```
┌─────────────────────────────────────────────┐
│  Docker Container (freecad-custom)          │
│                                             │
│  ┌──────────────┐  ┌─────────────────────┐  │
│  │ FreeCAD 1.1.3│  │ noVNC (port 6080)   │  │
│  │ (GUI + RPC)  │←─│ WebSocket proxy     │  │
│  │  port 9875   │  └─────────────────────┘  │
│  └──────┬───────┘                           │
│         │ XML-RPC                           │
│  ┌──────┴───────┐  ┌─────────────────────┐  │
│  │ Web UI       │  │ Chat Panel (1/3)    │  │
│  │ port 9876    │  │ → AI tasks          │  │
│  │ (2/3 VNC +   │  │ → FreeCAD RPC       │  │
│  │  1/3 Chat)   │  └─────────────────────┘  │
│  └──────────────┘                           │
└─────────────────────────────────────────────┘
         ↑
    http://localhost:9876
         ↑
    OpenClaw / MiMo v2.5
```

## Быстрый старт

```bash
# Собрать образ
docker build -t freecad-custom:latest .

# Запустить
docker run -d --name freecad \
  -p 6080:6080 \
  -p 9875:9875 \
  -p 9876:9876 \
  freecad-custom:latest

# Открыть веб-интерфейс
# http://localhost:9876
```

## Доступные порты

| Порт | Сервис | Описание |
|------|--------|----------|
| 6080 | noVNC | VNC-экран FreeCAD в браузере |
| 9875 | XML-RPC | API для управления FreeCAD |
| 9876 | Web UI | Единый интерфейс (экран + чат) |

## Управление через RPC

```python
import xmlrpc.client
proxy = xmlrpc.client.ServerProxy('http://localhost:9875')

# Выполнить Python-код в FreeCAD
proxy.execute_code('import FreeCAD; print(FreeCAD.Version())')

# Создать объекты
proxy.execute_code('''
import FreeCAD, Part
doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model")
box = doc.addObject("Part::Box", "Box")
doc.recompute()
''')
```

## Команды чата (примеры)

- `Создай куб 10x10x10 мм`
- `Создай цилиндр r=5mm h=20mm`
- `Покажи список объектов`
- `Удали Box`
- `Перемести Box x=10 y=20`
- `Экспортируй в STL`

## MiMo + OpenClaw интеграция

Модель MiMo v2.5 (Xiaomi) через Polza API используется для:
- Интерпретации команд пользователя на естественном языке
- Генерации Python-кода для FreeCAD
- Автоматизации 3D-моделирования

## Структура проекта

```
freecad-custom/
├── Dockerfile              # Ubuntu 22.04 + FreeCAD 1.1.3 AppImage
├── start-freecad.sh        # Entrypoint: Xvfb, VNC, FreeCAD, WebUI
├── startup_rpc.py          # RPC-сервер (XML-RPC, порт 9875)
├── freecad_mcp_settings.json
├── FreeCADMCP/             # MCP-аддон для FreeCAD
│   ├── Init.py
│   ├── InitGui.py
│   └── rpc_server/         # Ядро RPC-сервера
├── webui/                  # Веб-интерфейс
│   ├── index.html          # Split: 2/3 VNC + 1/3 Chat
│   └── server.js           # Node.js сервер + RPC-бридж
└── README.md
```

## Лицензия

MIT
