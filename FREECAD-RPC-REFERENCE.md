# FreeCAD RPC Reference

## Connection
```python
import xmlrpc.client
c = xmlrpc.client.ServerProxy('http://127.0.0.1:9875')
c.ping()  # → True
```

## Methods

| Method | Args | Returns |
|--------|------|---------|
| `ping` | — | `True` |
| `create_document(name)` | str | `{success, document_name}` |
| `list_documents` | — | `[str]` |
| `create_object(doc_name, obj_data)` | str, dict | `{success, object_name}` |
| `edit_object(doc, obj, props)` | str, str, dict | `{success, object_name}` |
| `delete_object(doc, obj)` | str, str | `{success, object_name}` |
| `get_objects(doc_name)` | str | `[str]` |
| `get_object(doc, obj)` | str, str | dict |
| `execute_code(code)` | str | `{success, message}` |
| `get_active_screenshot(path)` | str | dict |
| `get_parts_list` | — | list |
| `insert_part_from_library(path)` | str | dict |
| `run_fem_analysis(doc, analysis, timeout)` | str, str, int | dict |
| `reload_document(doc)` | str | `{success}` |

## Object Creation
```python
c.create_object('MyDoc', {
    'Type': 'Part::Box',
    'Name': 'MyCube',
    'Properties': {'Length': 10.0, 'Width': 5.0, 'Height': 3.0}
})
```

Common types: `Part::Box`, `Part::Sphere`, `Part::Cylinder`, `Part::Cone`, `Part::Torus`, `Part::Prism`, `Part::Pyramid`

## Code Execution
```python
c.execute_code('import FreeCAD; doc = FreeCAD.activeDocument(); print([o.Name for o in doc.Objects])')
```

## Screenshots
```python
c.get_active_screenshot('/workspace/screenshot.png')
```

## Infrastructure
- Container: `freecad-custom-1` (Docker)
- noVNC: http://localhost:6080/vnc.html
- RPC: http://127.0.0.1:9875
- FreeCAD: 1.1.3 (AppImage)
- Working dir inside container: /workspace
