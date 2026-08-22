#!/usr/bin/env node
/**
 * FreeCAD Web UI Server — VNC + Chat + RPC bridge + Session Memory
 * Chat proxied to AI Bridge (port 9877) for MiMo ↔ FreeCAD
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
const BRIDGE_HOST = process.env.BRIDGE_HOST || 'localhost';
const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || '9877', 10);
const SESSION_DIR = process.env.SESSION_DIR || '/var/log/freecad/sessions';
const CORS_ORIGIN = process.env.CORS_ORIGIN || '*';

// Ensure session directory exists
try { fs.mkdirSync(SESSION_DIR, { recursive: true }); } catch(e) {}

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
      var escaped = String(a).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      return '<param><value><string>' + escaped + '</string></value></param>';
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

// --- Session Memory ---
function getSessionPath(sessionId) {
  // Sanitize session ID to prevent path traversal
  var safe = sessionId.replace(/[^a-zA-Z0-9_-]/g, '');
  return path.join(SESSION_DIR, safe + '.json');
}

function loadSession(sessionId) {
  try {
    var data = fs.readFileSync(getSessionPath(sessionId), 'utf-8');
    return JSON.parse(data);
  } catch(e) {
    return { session_id: sessionId, messages: [], created: Date.now() };
  }
}

function saveSession(sessionId, messages) {
  var session = loadSession(sessionId);
  session.session_id = sessionId;
  session.messages = messages;
  session.updated = Date.now();
  if (!session.created) session.created = Date.now();
  try {
    fs.writeFileSync(getSessionPath(sessionId), JSON.stringify(session, null, 2));
    return true;
  } catch(e) {
    console.error('Session save error:', e.message);
    return false;
  }
}

function clearSession(sessionId) {
  try {
    fs.unlinkSync(getSessionPath(sessionId));
    return true;
  } catch(e) {
    return false;
  }
}

function listSessions() {
  try {
    var files = fs.readdirSync(SESSION_DIR).filter(function(f) { return f.endsWith('.json'); });
    return files.map(function(f) {
      try {
        var data = JSON.parse(fs.readFileSync(path.join(SESSION_DIR, f), 'utf-8'));
        return {
          session_id: data.session_id,
          messages: data.messages ? data.messages.length : 0,
          created: data.created,
          updated: data.updated
        };
      } catch(e) { return null; }
    }).filter(Boolean);
  } catch(e) { return []; }
}

// --- Parse JSON body ---
function parseBody(req) {
  return new Promise(function(resolve, reject) {
    var body = '';
    req.on('data', function(chunk) { body += chunk; });
    req.on('end', function() {
      try { resolve(JSON.parse(body)); }
      catch(e) { reject(new Error('Invalid JSON')); }
    });
  });
}

// --- Proxy to AI Bridge (SSE streaming) ---
function proxyToBridgeSSE(req, res) {
  var body = '';
  req.on('data', function(chunk) { body += chunk; });
  req.on('end', function() {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': CORS_ORIGIN
    });
    var bridgeReq = http.request({
      hostname: BRIDGE_HOST, port: BRIDGE_PORT,
      path: '/api/chat/stream', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
    }, function(bridgeRes) {
      bridgeRes.on('data', function(chunk) {
        res.write(chunk);
      });
      bridgeRes.on('end', function() { res.end(); });
    });
    bridgeReq.on('error', function(err) {
      res.write('event: error\ndata: ' + JSON.stringify({error: err.message}) + '\n\n');
      res.end();
    });
    bridgeReq.write(body);
    bridgeReq.end();
  });
}

// --- Proxy to AI Bridge ---
function proxyToBridge(req, res) {
  var body = '';
  req.on('data', function(chunk) { body += chunk; });
  req.on('end', function() {
    var bridgeReq = http.request({
      hostname: BRIDGE_HOST,
      port: BRIDGE_PORT,
      path: req.url,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
    }, function(bridgeRes) {
      var data = '';
      bridgeRes.on('data', function(chunk) { data += chunk; });
      bridgeRes.on('end', function() {
        res.writeHead(bridgeRes.statusCode, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': CORS_ORIGIN });
        res.end(data);
      });
    });
    bridgeReq.on('error', function(err) {
      try {
        var parsed = JSON.parse(body);
        rpcCall('execute_code', [parsed.message]).then(function(result) {
          var output = result.message || JSON.stringify(result);
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': CORS_ORIGIN });
          res.end(JSON.stringify({ reply: output, type: 'direct_rpc' }));
        }).catch(function(rpcErr) {
          res.writeHead(502, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': CORS_ORIGIN });
          res.end(JSON.stringify({ reply: 'AI Bridge unavailable and RPC error: ' + rpcErr.message, type: 'error' }));
        });
      } catch (e) {
        res.writeHead(502, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': CORS_ORIGIN });
        res.end(JSON.stringify({ reply: 'AI Bridge unavailable: ' + err.message, type: 'error' }));
      }
    });
    bridgeReq.write(body);
    bridgeReq.end();
  });
}

// --- HTTP proxy to noVNC ---
function proxyToVnc(req, res) {
  var opts = {
    hostname: VNC_HOST, port: VNC_PORT, path: req.url, method: req.method, headers: req.headers
  };
  opts.headers.host = VNC_HOST + ':' + VNC_PORT;
  var proxy = http.request(opts, function(proxyRes) {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });
  proxy.on('error', function(err) { res.writeHead(502); res.end('VNC proxy error: ' + err.message); });
  req.pipe(proxy);
}

// --- JSON response helper ---
function jsonResponse(res, data, status) {
  res.writeHead(status || 200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': CORS_ORIGIN });
  res.end(JSON.stringify(data));
}

// --- Main HTTP server ---
var server = http.createServer(function(req, res) {
  res.setHeader('Access-Control-Allow-Origin', CORS_ORIGIN);

  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(200, {
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type'
    });
    res.end();
    return;
  }

  var parsed = url.parse(req.url, true);

  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    fs.createReadStream(path.join(__dirname, 'index.html')).pipe(res);
    return;
  }

  // --- API Routes ---
  if (parsed.pathname === '/api/config') {
    jsonResponse(res, { vncHost: 'localhost', vncPort: String(PORT) });
    return;
  }

  if (parsed.pathname === '/api/chat/stream' && req.method === 'POST') {
    proxyToBridgeSSE(req, res);
    return;
  }

  if (parsed.pathname === '/api/chat' && req.method === 'POST') {
    proxyToBridge(req, res);
    return;
  }

  if (parsed.pathname === '/api/export' && req.method === 'POST') {
    proxyToBridge(req, res);
    return;
  }

  if (parsed.pathname === '/api/execute' && req.method === 'POST') {
    proxyToBridge(req, res);
    return;
  }

  if (parsed.pathname === '/api/feedback' && req.method === 'POST') {
    proxyToBridge(req, res);
    return;
  }

  if (parsed.pathname === '/api/new' && req.method === 'POST') {
    proxyToBridge(req, res);
    return;
  }

  if (parsed.pathname === '/api/rpc-test') {
    rpcCall('execute_code', ['import FreeCAD; print(FreeCAD.Version())']).then(function(result) {
      jsonResponse(res, { ok: true, result: result });
    }).catch(function(err) {
      jsonResponse(res, { ok: false, error: err.message });
    });
    return;
  }

  // --- Session Memory API ---
  if (parsed.pathname === '/api/session/save' && req.method === 'POST') {
    parseBody(req).then(function(body) {
      var ok = saveSession(body.session_id, body.messages || []);
      jsonResponse(res, { ok: ok });
    }).catch(function(e) {
      jsonResponse(res, { ok: false, error: e.message }, 400);
    });
    return;
  }

  if (parsed.pathname === '/api/session/load' && req.method === 'GET') {
    var sessionId = parsed.query.session_id;
    if (!sessionId) { jsonResponse(res, { error: 'session_id required' }, 400); return; }
    var session = loadSession(sessionId);
    jsonResponse(res, session);
    return;
  }

  if (parsed.pathname === '/api/session/clear' && req.method === 'POST') {
    parseBody(req).then(function(body) {
      var ok = clearSession(body.session_id);
      jsonResponse(res, { ok: ok });
    }).catch(function(e) {
      jsonResponse(res, { ok: false, error: e.message }, 400);
    });
    return;
  }

  if (parsed.pathname === '/api/session/list') {
    jsonResponse(res, { sessions: listSessions() });
    return;
  }

  // Everything else → proxy to noVNC
  proxyToVnc(req, res);
});

// --- WebSocket proxy for noVNC ---
server.on('upgrade', function(req, socket, head) {
  var opts = { hostname: VNC_HOST, port: VNC_PORT, path: req.url, method: 'GET', headers: req.headers };
  var proxyReq = http.request(opts);
  proxyReq.on('upgrade', function(proxyRes, proxySocket, proxyHead) {
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
  proxyReq.on('error', function() { socket.destroy(); });
  proxyReq.end();
});

server.listen(PORT, '0.0.0.0', function() {
  console.log('FreeCAD Web UI: http://localhost:' + PORT);
  console.log('  Chat -> AI Bridge at ' + BRIDGE_HOST + ':' + BRIDGE_PORT);
  console.log('  VNC proxied from ' + VNC_HOST + ':' + VNC_PORT);
  console.log('  Sessions stored in ' + SESSION_DIR);
});
