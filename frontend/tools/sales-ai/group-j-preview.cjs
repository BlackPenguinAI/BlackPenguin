// Local build preview only. No API proxy, production data or external services.
const http=require('node:http');const fs=require('node:fs');const path=require('node:path');
const root=path.resolve(__dirname,'../../dist/frontend/browser');
if(!fs.existsSync(path.join(root,'index.html')))throw Error('Build frontend first');
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2'};
const server=http.createServer((req,res)=>{
 let name;try{name=decodeURIComponent(new URL(req.url,'http://localhost').pathname);}catch{res.writeHead(400).end();return;}
 const file=path.resolve(root,'.'+name);
 if(!file.startsWith(root+path.sep)&&file!==root){res.writeHead(403).end();return;}
 if(name.startsWith('/api/')){res.writeHead(501).end('API must be mocked by the browser harness');return;}
 const target=fs.existsSync(file)&&fs.statSync(file).isFile()?file:path.extname(name)?null:path.join(root,'index.html');
 if(!target){res.writeHead(404).end();return;}
 res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream','Cache-Control':'no-store'});fs.createReadStream(target).pipe(res);
});
server.listen(4180,'127.0.0.1',()=>console.log('Group J synthetic preview ready on http://127.0.0.1:4180'));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>server.close(()=>process.exit(0)));
