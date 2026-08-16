#!/usr/bin/env node
/**
 * FreeCAD Web UI Server — VNC + Chat + RPC bridge
 * Proxies HTTP and WebSocket to noVNC (port 6080)
 * Compatible with Node.js 12+
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = parseInt(process.env.WEBUI_PORT || '9876', 10);
const VNC_HOST = process.env.VNC_HOST || 'localhost';
const VNC_PORT = parseInt(process.env.NOVNC_PORT || process.env.VNC_PORT || '6080', 10);
const RPC_HOST = process.env.RPC_HOST || 'localhost';
const RPC_PORT = parseInt(process.env.RPC_PORT || '9875', 10);

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Parse XML-RPC struct response
function parseXmlRpcResponse(xml) {
  var faultMatch = xml.match(/<fault>([\s\S]*?)<\/fault>/);
  if (faultMatch) {
    var faultStr = faultMatch[1].match(/<string>([\s\S]*?)<\/string>/);
    throw new Error(faultStr ? faultStr[1] : 'RPC fault');
  }
  var structStart = xml.indexOf('<struct>');
  var structEnd = xml.indexOf('</struct>');
  if (structStart === -1 || structEnd === -1) {
    var s = xml.match(/<string>([\s\S]*?)<\/string>/);
    if (s) return s[1];
    return xml;
  }
  var structBody = xml.substring(structStart + 8, structEnd);
  var result = {};
  var memberRegex = /<member>([\s\S]*?)<\/member>/g;
  var m;
  while ((m = memberRegex.exec(structBody)) !== null) {
    var memberXml = m[1];
    var nameMatch = memberXml.match(/<name>([\s\S]*?)<\/name>/);
    if (!nameMatch) continue;
    var name = nameMatch[1].trim();
    var valueStr = memberXml.match(/<value>\s*<string>([\s\S]*?)<\/string>\s*<\/value>/);
    var valueBool = memberXml.match(/<value>\s*<boolean>([\s\S]*?)<\/boolean>\s*<\/value>/);
    if (valueStr) result[name] = valueStr[1];
    else if (valueBool) result[name] = valueBool[1] === '1';
    else {
      var valMatch = memberXml.match(/<value>([\s\S]*?)<\/value>/);
      if (valMatch) result[name] = valMatch[1].replace(/<[^>]+>/g, '').trim();
    }
  }
  return result;
}

function rpcCall(method, args) {
  args = args || [];
  return new Promise(function(resolve, reject) {
    var argsXml = args.map(function(a) {
      return '<param><value><string>' + escapeXml(String(a)) + '</string></value></param>';
    }).join('');
    var body = '<?xml version="1.0"?><methodCall><methodName>' + method + '</methodName><params>' + argsXml + '</params></methodCall>';
    var req = http.request({
      hostname: RPC_HOST, port: RPC_PORT, path: '/', method: 'POST',
      headers: { 'Content-Type': 'text/xml', 'Content-Length': Buffer.byteLength(body) }
    }, function(res) {
      var data = '';
      res.on('data', function(chunk) { data += chunk; });
      res.on('end', function() {
        try { resolve(parseXmlRpcResponse(data)); }
        catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function handleChat(message) {
  var lower = message.toLowerCase();
  var code = '', desc = '';

  if (lower.indexOf('\u043a\u0443\u0431') !== -1) { // куб
    var sz = message.match(/(\d+(?:\.\d+)?)\s*(?:x|\u00d7)\s*(\d+(?:\.\d+)?)\s*(?:x|\u00d7)\s*(\d+(?:\.\d+)?)/);
    var sx = sz ? sz[1] : '10', sy = sz ? sz[2] : '10', szz = sz ? sz[3] : '10';
    code = 'import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); b = doc.addObject("Part::Box","Box"); b.Length=' + sx + '; b.Width=' + sy + '; b.Height=' + szz + '; doc.recompute(); print("Box " + str(b.Length) + "x" + str(b.Width) + "x" + str(b.Height))';
    desc = 'Box ' + sx + '\u00d7' + sy + '\u00d7' + szz;
  }
  else if (lower.indexOf('\u0446\u0438\u043b\u0438\u043d\u0434\u0440') !== -1) { // цилиндр
    var r = (message.match(/r\s*=\s*(\d+(?:\.\d+)?)/) || [])[1] || '5';
    var h = (message.match(/h\s*=\s*(\d+(?:\.\d+)?)/) || [])[1] || '20';
    code = 'import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); c = doc.addObject("Part::Cylinder","Cylinder"); c.Radius=' + r + '; c.Height=' + h + '; doc.recompute(); print("Cylinder r=" + str(c.Radius) + " h=" + str(c.Height))';
    desc = 'Cylinder r=' + r + ' h=' + h;
  }
  else if (lower.indexOf('\u0441\u0444\u0435\u0440\u0430') !== -1) { // сфера
    var rs = (message.match(/r\s*=\s*(\d+(?:\.\d+)?)/) || [])[1] || '10';
    code = 'import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); s = doc.addObject("Part::Sphere","Sphere"); s.Radius=' + rs + '; doc.recompute(); print("Sphere r=" + str(s.Radius))';
    desc = 'Sphere r=' + rs;
  }
  else if (lower.indexOf('\u0441\u043f\u0438\u0441\u043e\u043a') !== -1 || lower.indexOf('\u043e\u0431\u044a\u0435\u043a\u0442') !== -1) { // список / объект
    code = 'import FreeCAD; doc = FreeCAD.activeDocument(); print(", ".join([o.Name+" ("+o.TypeId+")" for o in doc.Objects]) if doc else "empty")';
    desc = 'Objects';
  }
  else if (lower.indexOf('stl') !== -1 || lower.indexOf('\u044d\u043a\u0441\u043f\u043e\u0440\u0442') !== -1) {
    code = 'import FreeCAD, Import; doc = FreeCAD.activeDocument(); Import.export(doc.Objects, "/tmp/model.stl"); print("Exported " + str(len(doc.Objects)) + " objects")';
    desc = 'STL export';
  }
  else {
    code = message;
    desc = 'Code';
  }

  return rpcCall('execute_code', [code]).then(function(result) {
    return { reply: '\u2705 ' + desc + '\n\n' + (result.message || JSON.stringify(result)) };
  }).catch(function(err) {
    return { error: err.message };
  });
}

// --- HTTP proxy to noVNC ---
function proxyToVnc(req, res) {
  var opts = {
    hostname: VNC_HOST,
    port: VNC_PORT,
    path: req.url,
    method: req.method,
    headers: req.headers
  };
  // Rewrite Host header
  opts.headers.host = VNC_HOST + ':' + VNC_PORT;

  var proxy = http.request(opts, function(proxyRes) {
    // Add CORS headers
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });
  proxy.on('error', function(err) {
    res.writeHead(502);
    res.end('VNC proxy error: ' + err.message);
  });
  req.pipe(proxy);
}

// --- Main HTTP server ---
var server = http.createServer(function(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');

  // API routes
  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    fs.createReadStream(path.join(__dirname, 'index.html')).pipe(res);
    return;
  }
  if (req.url === '/api/config') {
    // Return the SAME port — noVNC WebSocket will go through same origin
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ vncHost: 'localhost', vncPort: String(PORT) }));
    return;
  }
  if (req.url === '/api/chat' && req.method === 'POST') {
    var body = '';
    req.on('data', function(chunk) { body += chunk; });
    req.on('end', function() {
      try {
        var parsed = JSON.parse(body);
        handleChat(parsed.message).then(function(result) {
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify(result));
        }).catch(function(err) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: err.message }));
        });
      } catch (err) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
    return;
  }
  if (req.url === '/api/rpc-test') {
    rpcCall('execute_code', ['import FreeCAD; print(FreeCAD.Version())']).then(function(result) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, result: result }));
    }).catch(function(err) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: err.message }));
    });
    return;
  }

  // Everything else → proxy to noVNC (static files + WebSocket)
  proxyToVnc(req, res);
});

// --- WebSocket proxy for noVNC ---
server.on('upgrade', function(req, socket, head) {
  var opts = {
    hostname: VNC_HOST,
    port: VNC_PORT,
    path: req.url,
    method: 'GET',
    headers: req.headers
  };

  var proxyReq = http.request(opts);
  proxyReq.on('upgrade', function(proxyRes, proxySocket, proxyHead) {
    // Build raw HTTP 101 response
    var rawHead = 'HTTP/1.1 101 Switching Protocols\r\n';
    Object.keys(proxyRes.headers).forEach(function(key) {
      rawHead += key + ': ' + proxyRes.headers[key] + '\r\n';
    });
    rawHead += '\r\n';

    socket.write(rawHead);
    if (proxyHead.length > 0) socket.write(proxyHead);

    proxySocket.pipe(socket);
    socket.pipe(proxySocket);

    proxySocket.on('error', function() { socket.destroy(); });
    socket.on('error', function() { proxySocket.destroy(); });
    proxySocket.on('close', function() { socket.destroy(); });
    socket.on('close', function() { proxySocket.destroy(); });
  });

  proxyReq.on('error', function(err) {
    socket.destroy();
  });

  proxyReq.end();
});

server.listen(PORT, '0.0.0.0', function() {
  console.log('FreeCAD Web UI: http://localhost:' + PORT);
  console.log('  VNC proxied from ' + VNC_HOST + ':' + VNC_PORT);
  console.log('  RPC at ' + RPC_HOST + ':' + RPC_PORT);
});
