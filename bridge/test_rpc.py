import http.client

# Test RPC
try:
    conn = http.client.HTTPConnection('localhost', 9875, timeout=5)
    body = '<?xml version="1.0"?><methodCall><methodName>ping</methodName><params></params></methodCall>'
    conn.request('POST', '/', body, {'Content-Type': 'text/xml'})
    resp = conn.getresponse()
    print('RPC ping:', resp.read().decode()[:200])
except Exception as e:
    print('RPC error:', e)

# Test screenshot code
try:
    code = 'import FreeCADGui, tempfile, os; path = os.path.join(tempfile.gettempdir(), "test_ss.png"); FreeCADGui.ActiveDocument.ActiveView.saveImage(path, 800, 600, "PNG"); print("OK:" + path)'
    escaped = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    body2 = '<?xml version="1.0"?><methodCall><methodName>execute_code</methodName><params><param><value><string>' + escaped + '</string></value></param></params></methodCall>'
    conn2 = http.client.HTTPConnection('localhost', 9875, timeout=10)
    conn2.request('POST', '/', body2, {'Content-Type': 'text/xml'})
    resp2 = conn2.getresponse()
    print('Screenshot:', resp2.read().decode()[:500])
except Exception as e:
    print('Screenshot error:', e)
