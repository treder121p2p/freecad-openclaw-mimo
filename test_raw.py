import http.client
c = http.client.HTTPConnection('localhost', 9875)
body = '''<?xml version="1.0"?>
<methodCall>
<methodName>execute_code</methodName>
<params>
<param><value><string>import FreeCAD; print("hello")</string></value></param>
</params>
</methodCall>'''
c.request('POST', '/', body, {'Content-Type': 'text/xml'})
r = c.getresponse()
data = r.read().decode()
print(data)
