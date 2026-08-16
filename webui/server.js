#!/usr/bin/env node
/**
 * FreeCAD Web UI Server — VNC + Chat + RPC bridge
 * Port 9876: unified interface
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PORT = parseInt(process.env.WEBUI_PORT || '9876', 10);
const VNC_HOST = process.env.VNC_HOST || 'localhost';
const VNC_PORT = process.env.VNC_PORT || '6080';
const RPC_HOST = process.env.RPC_HOST || 'localhost';
const RPC_PORT = parseInt(process.env.RPC_PORT || '9875', 10);

// --- XML-RPC client for FreeCAD ---
function rpcCall(method, args = []) {
  return new Promise((resolve, reject) => {
    const argsXml = args.map(a => `<param><value><string>${escapeXml(String(a))}</string></value></param>`).join('');
    const body = `<?xml version="1.0"?><methodCall><methodName>${method}</methodName><params>${argsXml}</params></methodCall>`;

    const req = http.request({
      hostname: RPC_HOST,
      port: RPC_PORT,
      path: '/',
      method: 'POST',
      headers: {
        'Content-Type': 'text/xml',
        'Content-Length': Buffer.byteLength(body)
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          // Parse XML-RPC response
          const faultMatch = data.match(/<fault>([\s\S]*?)<\/fault>/);
          if (faultMatch) {
            const faultStr = faultMatch[1].match(/<string>([\s\S]*?)<\/string>/);
            reject(new Error(faultStr ? faultStr[1] : 'RPC fault'));
            return;
          }
          const valueMatch = data.match(/<param>([\s\S]*?)<\/param>/);
          if (valueMatch) {
            // Try struct
            const structMatch = valueMatch[1].match(/<struct>([\s\S]*?)<\/struct>/);
            if (structMatch) {
              const result = {};
              const members = structMatch[1].match(/<member>([\s\S]*?)<\/member>/g) || [];
              for (const m of members) {
                const name = m.match(/<name>(.*?)<\/name>/)?.[1];
                const val = m.match(/<value>([\s\S]*?)<\/value>/)?.[1];
                const str = val?.match(/<string>([\s\S]*?)<\/string>/)?.[1] ||
                           val?.match(/<boolean>(.*?)<\/boolean>/)?.[1] ||
                           val?.match(/<int>(.*?)<\/int>/)?.[1] ||
                           val?.match(/<double>(.*?)<\/double>/)?.[1] || '';
                if (name) result[name] = str;
              }
              resolve(result);
              return;
            }
            // Simple value
            const str = valueMatch[1].match(/<string>([\s\S]*?)<\/string>/)?.[1] ||
                       valueMatch[1].match(/<boolean>(.*?)<\/boolean>/)?.[1] ||
                       valueMatch[1].match(/<int>(.*?)<\/int>/)?.[1] || valueMatch[1];
            resolve(str);
          } else {
            resolve(data);
          }
        } catch (e) {
          reject(e);
        }
      });
    });

    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function escapeXml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// --- Chat logic: user message → FreeCAD RPC execution ---
async function handleChat(message, history) {
  // Map user intent to FreeCAD Python code
  const lower = message.toLowerCase();

  // Simple pattern matching for common tasks
  let code = '';
  let description = '';

  if (lower.includes('создай куб') || lower.includes('добавь куб') || lower.includes('куб')) {
    const sizeMatch = message.match(/(\d+(?:\.\d+)?)\s*(?:x|×)\s*(\d+(?:\.\d+)?)\s*(?:x|×)\s*(\d+(?:\.\d+)?)/);
    const size = sizeMatch ? [sizeMatch[1], sizeMatch[2], sizeMatch[3]] : ['10', '10', '10'];
    code = `import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); box = doc.addObject("Part::Box", "Box"); box.Length = ${size[0]}; box.Width = ${size[1]}; box.Height = ${size[2]}; doc.recompute(); print(f"Created Box: {box.Length}x{box.Width}x{box.Height} mm")`;
    description = `Создаю куб ${size[0]}×${size[1]}×${size[2]} мм`;
  }
  else if (lower.includes('цилиндр')) {
    const rMatch = message.match(/r\s*=\s*(\d+(?:\.\d+)?)/);
    const hMatch = message.match(/h\s*=\s*(\d+(?:\.\d+)?)/);
    const r = rMatch ? rMatch[1] : '5';
    const h = hMatch ? hMatch[1] : '20';
    code = `import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); cyl = doc.addObject("Part::Cylinder", "Cylinder"); cyl.Radius = ${r}; cyl.Height = ${h}; doc.recompute(); print(f"Created Cylinder: r={cyl.Radius}, h={cyl.Height}")`;
    description = `Создаю цилиндр r=${r} мм, h=${h} мм`;
  }
  else if (lower.includes('сфера')) {
    const rMatch = message.match(/r\s*=\s*(\d+(?:\.\d+)?)/);
    const r = rMatch ? rMatch[1] : '10';
    code = `import FreeCAD, Part; doc = FreeCAD.activeDocument() or FreeCAD.newDocument("Model"); sphere = doc.addObject("Part::Sphere", "Sphere"); sphere.Radius = ${r}; doc.recompute(); print(f"Created Sphere: r={sphere.Radius}")`;
    description = `Создаю сферу r=${r} мм`;
  }
  else if (lower.includes('список объектов') || lower.includes('покажи объекты') || lower.includes('что есть')) {
    code = `import FreeCAD; doc = FreeCAD.activeDocument(); objs = [f"{o.Name} ({o.TypeId})" for o in doc.Objects] if doc else []; print("Objects: " + (", ".join(objs) if objs else "No document or empty"))`;
    description = 'Получаю список объектов...';
  }
  else if (lower.includes('скриншот') || lower.includes('скрин')) {
    code = `import FreeCADGui; FreeCADGui.ActiveDocument.ActiveView.saveImage("/tmp/freecad_screenshot.png"); print("Screenshot saved to /tmp/freecad_screenshot.png")`;
    description = 'Делаю скриншот...';
  }
  else if (lower.includes('stl') || lower.includes('экспорт')) {
    code = `import FreeCAD, Part, Import; doc = FreeCAD.activeDocument(); objs = doc.Objects if doc else []; Import.export(objs, "/tmp/model.stl"); print(f"Exported {len(objs)} objects to /tmp/model.stl")`;
    description = 'Экспортирую в STL...';
  }
  else if (lower.includes('удали') || lower.includes('убери')) {
    const nameMatch = message.match(/["']?(\w+)["']?\s*$/);
    const name = nameMatch ? nameMatch[1] : '';
    if (name) {
      code = `import FreeCAD; doc = FreeCAD.activeDocument(); obj = doc.getObject("${name}"); doc.removeObject("${name}") if obj else None; doc.recompute(); print(f"Deleted: ${name}")`;
      description = `Удаляю объект ${name}`;
    } else {
      return { reply: 'Укажите имя объекта для удаления, например: "Удали Box"' };
    }
  }
  else if (lower.includes('перемести') || lower.includes('сдвинь')) {
    const nameMatch = message.match(/["']?(\w+)["']?/);
    const xMatch = message.match(/x\s*[=:]\s*(-?\d+(?:\.\d+)?)/);
    const yMatch = message.match(/y\s*[=:]\s*(-?\d+(?:\.\d+)?)/);
    const zMatch = message.match(/z\s*[=:]\s*(-?\d+(?:\.\d+)?)/);
    const name = nameMatch ? nameMatch[1] : '';
    const x = xMatch ? xMatch[1] : '0';
    const y = yMatch ? yMatch[1] : '0';
    const z = zMatch ? zMatch[1] : '0';
    if (name) {
      code = `import FreeCAD; doc = FreeCAD.activeDocument(); obj = doc.getObject("${name}"); obj.Placement.Base = FreeCAD.Vector(${x}, ${y}, ${z}); doc.recompute(); print(f"Moved ${name} to ({x}, {y}, {z})")`;
      description = `Перемещаю ${name} в (${x}, ${y}, ${z})`;
    } else {
      return { reply: 'Укажите имя объекта, например: "Перемести Box x=10 y=20"' };
    }
  }
  else if (lower.includes('объедини') || lower.includes('boolean') || lower.includes('sum')) {
    code = `import FreeCAD, Part; doc = FreeCAD.activeDocument(); objs = doc.Objects; fuses = []; [fuses.append(Part.Shape(objs[i].Shape).fuse(Part.Shape(objs[i+1].Shape))) for i in range(len(objs)-1)]; print(f"Fused {len(objs)} objects") if fuses else print("Need 2+ objects")`;
    description = 'Объединяю объекты...';
  }
  else {
    // Generic: execute as FreeCAD Python code
    code = message;
    description = `Выполняю: ${message}`;
  }

  // Execute via RPC
  try {
    const result = await rpcCall('execute_code', [code]);
    const output = result.message || result || 'Done';
    return { reply: `✅ ${description}\n\n${output}` };
  } catch (err) {
    return { error: err.message };
  }
}

// --- HTTP Server ---
const server = http.createServer(async (req, res) => {
  // CORS
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
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', async () => {
      try {
        const { message, history } = JSON.parse(body);
        const result = await handleChat(message, history || []);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      } catch (err) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
  }
  else if (req.url === '/api/rpc-test') {
    try {
      const result = await rpcCall('execute_code', ['import FreeCAD; print(FreeCAD.Version())']);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, result }));
    } catch (err) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: err.message }));
    }
  }
  else {
    // Static files from webui dir
    const filePath = path.join(__dirname, req.url);
    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      const ext = path.extname(filePath);
      const types = { '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png' };
      res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain' });
      fs.createReadStream(filePath).pipe(res);
    } else {
      res.writeHead(404);
      res.end('Not found');
    }
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`FreeCAD Web UI: http://localhost:${PORT}`);
  console.log(`  VNC → ${VNC_HOST}:${VNC_PORT}`);
  console.log(`  RPC → ${RPC_HOST}:${RPC_PORT}`);
});
