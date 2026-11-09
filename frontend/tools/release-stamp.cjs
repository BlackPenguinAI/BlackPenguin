// Public build identity only. No environment values other than the commit are exported.
const fs=require('node:fs');const path=require('node:path');const crypto=require('node:crypto');
function stamp(root,commit='unknown') {
 if(commit!=='unknown'&&!/^[0-9a-f]{40}$/.test(commit))throw Error('Use a full lowercase Git SHA or unknown');
 if(!fs.existsSync(path.join(root,'index.html')))throw Error('Build index.html is missing');
 const files=[];
 function walk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0)){
  const file=path.join(dir,entry.name);if(entry.isSymbolicLink())throw Error('Build symlinks are not supported');
  if(entry.isDirectory())walk(file);else if(entry.isFile()&&file!==path.join(root,'release.json'))files.push(file);
 }}walk(root);
 const hash=crypto.createHash('sha256');
 for(const file of files){hash.update(path.relative(root,file).split(path.sep).join('/'));hash.update('\0');hash.update(crypto.createHash('sha256').update(fs.readFileSync(file)).digest());}
 const result={version:'blackpenguin.frontend-release/1.0',service:'frontend',commit,commit_known:commit!=='unknown',assets_sha256:hash.digest('hex'),asset_count:files.length};
 fs.writeFileSync(path.join(root,'release.json'),JSON.stringify(result,null,2)+'\n');return result;
}
if(require.main===module){const root=path.resolve(__dirname,'../dist/frontend/browser');console.log(JSON.stringify(stamp(root,process.env.APP_COMMIT_SHA||'unknown')));}
module.exports={stamp};
