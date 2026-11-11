const fs=require('node:fs'),path=require('node:path');
const asar=require(process.env.ASAR_MODULE);
const [input,output]=process.argv.slice(2);
let count=0;
for(const name of asar.listPackage(input)){
 const rel=name.replace(/^\//,'');
 if(!rel.startsWith('renderer/openflow/')||!/\.(mp4|glb)$/.test(rel))continue;
 const dest=path.resolve(output,rel.slice('renderer/'.length));
 if(!dest.startsWith(path.resolve(output)+path.sep))throw Error('Unsafe asset path');
 fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,asar.extractFile(input,rel));count++;
}
console.log('Restored '+count+' already-published media assets.');
