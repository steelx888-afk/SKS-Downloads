// Publish the reusable fixed macOS installer and the metadata key the SKS SI
// download route reads. The application owns the versioned universal build;
// this only adds the stable `SKS-<APP>-latest-universal.dmg` publication point
// so one download URL always serves the newest verified installer.
import {readFileSync,writeFileSync,existsSync,copyFileSync,linkSync,rmSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import path from 'node:path';

const arg=name=>process.argv.find(item=>item.startsWith(`--${name}=`))?.slice(name.length+3);
const app=arg('app');
const source=path.resolve(arg('source')||'private-source');
const directory=path.resolve(arg('directory')||path.join(process.env.RUNNER_TEMP||'.','publish'));
if(!['lab','designz','proz'].includes(app))throw new Error(`Unknown application: ${app}.`);
const repository='steelx888-afk/SKS-Downloads';
const tag=`${app}-latest`;
const metadataName='latest-mac.yml';
function gh(args,optional=false){
 const result=spawnSync('gh',args,{encoding:'utf8',maxBuffer:32*1024*1024});
 if(result.status!==0&&!optional)throw new Error(`gh ${args.slice(0,3).join(' ')} failed: ${(result.stderr||result.stdout||'').trim()}`);
 return result;
}
const manifest=JSON.parse(readFileSync(path.join(source,'apps/desktop/package.json'),'utf8'));
if(manifest.sks?.id!==app)throw new Error(`The checked out source is ${manifest.sks?.id}, not ${app}.`);
const version=manifest.version,prefix=`SKS-${app.toUpperCase()}`;
const versionedDmg=`${prefix}-${version}-universal.dmg`,aliasDmg=`${prefix}-latest-universal.dmg`;
const metadataPath=path.join(directory,metadataName);
if(!existsSync(metadataPath))throw new Error(`Missing published update metadata at ${metadataPath}.`);
const release=JSON.parse(gh(['api',`repos/${repository}/releases/tags/${tag}`]).stdout);
if(!release||release.draft)throw new Error('The download release is still a draft.');
const asset=name=>release.assets?.find(item=>item.name===name&&item.state==='uploaded');
const versioned=asset(versionedDmg);
if(!versioned)throw new Error(`The versioned installer ${versionedDmg} is not published yet.`);
const existing=asset(aliasDmg);
if(existing&&versioned.digest&&existing.digest===versioned.digest){
 console.log(`Reusing the published fixed installer ${aliasDmg}.`);
}else{
 if(!existsSync(path.join(directory,versionedDmg)))throw new Error(`Missing local installer ${versionedDmg} for the fixed alias.`);
 const target=path.join(directory,aliasDmg);
 rmSync(target,{force:true});
 try{linkSync(path.join(directory,versionedDmg),target);}catch{copyFileSync(path.join(directory,versionedDmg),target);}
 gh(['release','upload',tag,'-R',repository,'--clobber',target]);
 console.log(`Published the reusable fixed installer ${aliasDmg} for ${version}.`);
}
const record=/^latest:\s*[^\r\n]*$/m;
let metadata=readFileSync(metadataPath,'utf8');
metadata=record.test(metadata)?metadata.replace(record,`latest: ${aliasDmg}`):metadata.replace(/\s*$/,'\n')+`latest: ${aliasDmg}\n`;
writeFileSync(metadataPath,metadata);
const published=gh(['release','download',tag,'-R',repository,'--pattern',metadataName,'--output','-'],true);
if(published.status!==0||published.stdout!==metadata){
 gh(['release','upload',tag,'-R',repository,'--clobber',metadataPath]);
 console.log('Republished the Mac update metadata with the reusable fixed installer.');
}
const mirror=spawnSync(process.execPath,[path.join(source,'apps/desktop/scripts/mirror-release-metadata.mjs'),'--platform=mac'],{cwd:source,stdio:'inherit'});
if(mirror.status!==0)throw new Error('The fixed installer is published, but the website metadata mirror needs a retry.');
console.log(`Fixed Mac installer and metadata are current for ${app} ${version}.`);
