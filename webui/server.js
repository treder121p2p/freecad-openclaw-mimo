#!/usr/bin/env node
/**
 * FreeCAD Web UI Server — VNC + Chat + RPC bridge
 * Compatible with Node.js 12+, robust XML-RPC parsing
 */

const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.env.WEBUI_PORT || '9876', 10);
const VNC_HOST = process.env.VNC_HOST || 'localhost';
const VNC_PORT = process.env.VNC_PORT || '6080';
const RPC_HOST = process.env.RPC_HOST || 'localhost';
const RPC_PORT = parseInt(process.env.RPC_PORT || '9875', 10);

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Parse XML-RPC response: extract struct members as key-value object
function parseXmlRpcResponse(xml) {
  // Check for fault
  var faultMatch = xml.match(/<fault>([\s\S]*?)<\/fault>/);
  if (faultMatch) {
    var faultStr = faultMatch[1].match(/<string>([\s\S]*?)<\/string>/);
    throw new Error(faultStr ? faultStr[1] : 'RPC fault');
  }

  // Find struct members - iterate through all <member> blocks
  var structStart = xml.indexOf('<struct>');
  var structEnd = xml.indexOf('</struct>');
  if (structStart === -1 || structEnd === -1) {
    // Not a struct, try simple value
    var s = xml.match(/<string>([\s\S]*?)<\/string>/);
    if (s) return s[1];
    var b = xml.match(/<boolean>([\s\S]*?)<\/boolean>/);
    if (b) return b[1];
    var i = xml.match(/<int>([\s\S]*?)<\/int>/);
    if (i) return i[1];
    return xml;
  }

  var structBody = xml.substring(structStart + 8, structEnd);
  var result = {};

  // Split by <member> tags
  var memberRegex = /<member>([\s\S]*?)<\/member>/g;
  var m;
  while ((m = memberRegex.exec(structBody)) !== null) {
    var memberXml = m[1];
    var nameMatch = memberXml.match(/<name>([\s\S]*?)<\/name>/);
    if (!nameMatch) continue;
    var name = nameMatch[1].trim();

    // Extract value - could be string, boolean, int, double, or nested struct
    var valueStr = memberXml.match(/<value>\s*<string>([\s\S]*?)<\/string>\s*<\/value>/);
    var valueBool = memberXml.match(/<value>\s*<boolean>([\s\S]*?)<\/boolean>\s*<\/value>/);
    var valueInt = memberXml.match(/<value>\s*<int>([\s\S]*?)<\/int>\s*<\/value>/);
    var valueDouble = memberXml.match(/<value>\s*<double>([\s\S]*?)<\/double>\s*<\/value>/);

    if (valueStr) result[name] = valueStr[1];
    else if (valueBool) result[name] = valueBool[1] === '1' || valueBool[1] === 'true';
    else if (valueInt) result[name] = parseInt(valueInt[1], 10);
    else if (valueDouble) result[name] = parseFloat(valueDouble[1]);
    else {
      // Fallback: extract anything between <value> tags
      var valMatch = memberXml.match(/<value>([\s\S]*?)<\/value>/);
      if (valMatch) {
        var inner = valMatch[1].trim();
        // Strip any XML tags for simple values
        var stripped = inner.replace(/<[^>]+>/g, '').trim();
        result[name] = stripped;
      }
    }
  }

  return result;
}

// --- XML-RPC client ---
function rpcCall(method, args) {
  args = args || [];
  return new Promise(function(resolve, reject) {
    var argsXml = args.map(function(a) {
      return '<param><value><string>' + escapeXml(String(a)) + '</string></value></param>';
    }).join('');
    var body = '<?xml version="1.0"?><methodCall><methodName>' + method + '</methodName><params>' + argsXml + '</params></methodCall>';

    var req = http.request({
      hostname: RPC_HOST,
      port: RPC_PORT,
      path: '/',
      method: 'POST',
      headers: { 'Content-Type': 'text/xml', 'Content-Length': Buffer.byteLength(body) }
    }, function(res) {
      var data = '';
      res.on('data', function(chunk) { data += chunk; });
      res.on('end', function() {
        try {
          var result = parseXmlRpcResponse(data);
          resolve(result);
        } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// --- Chat logic ---
function handleChat(message) {
  var lower = message.toLowerCase();
  var code = '';
  var description = '';

  if (lower.indexOf('куб') !== -1) {
    var sizeMatch = message.match(/(\d+(?:\.\d+)?)\s*(?:x|×)\s*(\d+(?:\.\d+)?)\s*(?:x|×)\s*(\d+(?:\.\d+)?)/);
    var sx = sizeMatch ? sizeMatch[1] : '10';
    var sy = sizeMatch ? sizeMatch[2] : '10';
    var sz = sizeMatch ? sizeMatch[3] : '10';
    code = 'import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); box = doc.addObject("Part::Box", "Box"); box.Length = ' + sx + '; box.Width = ' + sy + '; box.Height = ' + sz + '; doc.recompute(); print("Created Box: " + str(box.Length) + "x" + str(box.Width) + "x" + str(box.Height))';
    description = 'Создаю куб ' + sx + '×' + sy + '×' + sz + ' мм';
  }
  else if (lower.indexOf('цилиндр') !== -1) {
    var rMatch = message.match(/r\s*=\s*(\d+(?:\.\d+)?)/);
    var hMatch = message.match(/h\s*=\s*(\d+(?:\.\d+)?)/);
    var r = rMatch ? rMatch[1] : '5';
    var h = hMatch ? hMatch[1] : '20';
    code = 'import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); cyl = doc.addObject("Part::Cylinder", "Cylinder"); cyl.Radius = ' + r + '; cyl.Height = ' + h + '; doc.recompute(); print("Created Cylinder r=" + str(cyl.Radius) + " h=" + str(cyl.Height))';
    description = 'Создаю цилиндр r=' + r + ', h=' + h + ' мм';
  }
  else if (lower.indexOf('сфера') !== -1) {
    var rs = (message.match(/r\s*=\s*(\d+(?:\.\d+)?)/) || [])[1] || '10';
    code = 'import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); sph = doc.addObject("Part::Sphere", "Sphere"); sph.Radius = ' + rs + '; doc.recompute(); print("Created Sphere r=" + str(sph.Radius))';
    description = 'Создаю сферу r=' + rs + ' мм';
  }
  else if (lower.indexOf('список') !== -1 || lower.indexOf('объект') !== -1 || lower.indexOf('что есть') !== -1) {
    code = 'import FreeCAD; doc = FreeCAD.activeDocument(); objs = [o.Name + " (" + o.TypeId + ")" for o in doc.Objects] if doc else []; print("Objects: " + (", ".join(objs) if objs else "No document or empty"))';
    description = 'Получаю список объектов...';
  }
  else if (lower.indexOf('скрин') !== -1) {
    code = 'import FreeCADGui; FreeCADGui.ActiveDocument.ActiveView.saveImage("/tmp/screenshot.png"); print("Screenshot saved")';
    description = 'Делаю скриншот...';
  }
  else if (lower.indexOf('stl') !== -1 || lower.indexOf('экспорт') !== -1) {
    code = 'import FreeCAD, Import; doc = FreeCAD.activeDocument(); Import.export(doc.Objects, "/tmp/model.stl"); print("Exported " + str(len(doc.Objects)) + " objects to STL")';
    description = 'Экспортирую в STL...';
  }
  else if (lower.indexOf('удали') !== -1 || lower.indexOf('убери') !== -1) {
    var nameMatch = message.match(/["\']?(\w+)["\']?\s*$/);
    var delName = nameMatch ? nameMatch[1] : '';
    if (delName) {
      code = 'import FreeCAD; doc = FreeCAD.activeDocument(); doc.removeObject("' + delName + '"); doc.recompute(); print("Deleted: ' + delName + '")';
      description = 'Удаляю ' + delName;
    } else {
      return Promise.resolve({ reply: 'Укажите имя объекта, например: "Удали Box"' });
    }
  }
  else if (lower.indexOf('перемести') !== -1 || lower.indexOf('сдвинь') !== -1) {
    var nm = (message.match(/["\']?(\w+)["\']?/) || [])[1] || '';
    var xv = (message.match(/x\s*[=:]\s*(-?\d+(?:\.\d+)?)/) || [])[1] || '0';
    var yv = (message.match(/y\s*[=:]\s*(-?\d+(?:\.\d+)?)/) || [])[1] || '0';
    var zv = (message.match(/z\s*[=:]\s*(-?\d+(?:\.\d+)?)/) || [])[1] || '0';
    if (nm) {
      code = 'import FreeCAD; doc = FreeCAD.activeDocument(); obj = doc.getObject("' + nm + '"); obj.Placement.Base = FreeCAD.Vector(' + xv + ', ' + yv + ', ' + zv + '); doc.recompute(); print("Moved ' + nm + '")';
      description = 'Перемещаю ' + nm;
    } else {
      return Promise.resolve({ reply: 'Укажите имя объекта, например: "Перемести Box x=10"' });
    }
  }
  else {
    code = message;
    description = 'Выполняю код...';
  }

  return rpcCall('execute_code', [code]).then(function(result) {
    var output = result.message || JSON.stringify(result) || 'Done';
    return { reply: '✅ ' + description + '\n\n' + output };
  }).catch(function(err) {
    return { error: err.message };
  });
}

// --- HTTP Server ---
var server = http.createServer(function(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    fs.createReadStream(path.join(__dirname, 'index.html')).pipe(res);
  }
  else if (req.url === '/api/config') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ vncHost: VNC_HOST, vncPort: VNC_PORT }));
  }
  else if (req.url === '/api/chat' && req.method === 'POST') {
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
  }
  else if (req.url === '/api/rpc-test') {
    rpcCall('execute_code', ['import FreeCAD; print(FreeCAD.Version())']).then(function(result) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, result: result }));
    }).catch(function(err) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: err.message }));
    });
  }
  else {
    res.writeHead(404);
    res.end('Not found');
  }
});

server.listen(PORT, '0.0.0.0', function() {
  console.log('FreeCAD Web UI: http://localhost:' + PORT);
});
