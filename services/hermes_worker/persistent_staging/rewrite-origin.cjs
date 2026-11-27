// Rewrite only staging build copies. Never touch the checked-out frontend.
const fs = require('fs'), path = require('path');
let authRewritten = false;
function walk(dir) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) { walk(p); continue; }
    if (!/\.(ts|html|js|json)$/.test(name)) continue;
    const before = fs.readFileSync(p,'utf8');
    let after = before.replace(/https?:\/\/(?:www\.)?blackpenguin\.ai\/api(?=\/|['"`])/gi,'/api');
    if (p.endsWith('/core/services/auth.ts')) {
      after = after.replace("return '/admin/dashboard'", "return '/admin/ai-settings/hermes'");
    }
    if (before !== after) {
      fs.writeFileSync(p,after);
      if (p.endsWith('/core/services/auth.ts')) authRewritten = true;
    }
    if (/https?:\/\/(?:www\.)?blackpenguin\.ai\/api(?=\/|['"`])/i.test(after)) throw new Error('Production API origin remains');
  }
}
walk(process.argv[2]);
if (!authRewritten) throw new Error('Review AuthService staging rewrite for changed baseline');
