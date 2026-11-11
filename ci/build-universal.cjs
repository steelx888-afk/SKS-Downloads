// The application owns dependency staging and installer configuration. Select
// its supported universal target through electron-builder's public API.
const path=require('node:path'),Module=require('node:module'),fs=require('node:fs');
const entry=fs.realpathSync(path.resolve(process.argv[2]));const from=Module.createRequire(entry),original=Module._load;
Module._load=function(name,parent,...rest){
 const value=original.call(this,name,parent,...rest);
 if(name==='electron-builder'&&parent?.filename===entry){
  const {Arch}=from('builder-util');
  return {...value,build:options=>value.build({...options,config:{...options.config,mac:{...options.config?.mac,minimumSystemVersion:process.env.SKS_MAC_MINIMUM_SYSTEM_VERSION}},targets:value.Platform.MAC.createTarget(['dmg','zip'],Arch.universal),publish:'never'})};
 }
 return value;
};
require(entry);Module._load=original;
