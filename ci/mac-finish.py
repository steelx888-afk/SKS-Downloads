import os,sys,json,pathlib,subprocess,hashlib,shutil,plistlib,time,signal,urllib.request,urllib.error,concurrent.futures
ROOT=pathlib.Path(__file__).resolve().parent.parent
CONFIG=json.loads((ROOT/'ci/mac-release-019.json').read_text(encoding='utf-8-sig'))
TEMP=pathlib.Path(os.environ['RUNNER_TEMP']);REPO='steelx888-afk/SKS-Downloads';TAG=os.environ['CACHE_TAG']
assert TAG.startswith('mac-native-cache-019-') and TAG.rsplit('-',1)[1].isdigit()
LOG=TEMP/('mac-finish-'+os.environ.get('PRODUCT','any')+'-'+os.environ.get('BUILD_ARCH','any')+'.log')
def command(args,cwd=None,env=None,capture=False):
 with LOG.open('a') as log:
  r=subprocess.run([str(a) for a in args],cwd=cwd,env=env,stdout=subprocess.PIPE if capture else log,stderr=log,text=True)
 if r.returncode:raise RuntimeError('Release command failed: '+pathlib.Path(str(args[0])).name+' (private log retained)')
 return r.stdout.strip() if capture else None
def upload(*files):command(['gh','release','upload',TAG,'-R',REPO,'--clobber',*files])
def download(pattern,folder):
 folder.mkdir(parents=True,exist_ok=True);command(['gh','release','download',TAG,'-R',REPO,'--pattern',pattern,'--dir',folder,'--clobber'])
def sha(file):
 with pathlib.Path(file).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def source_root(app):
 source=ROOT/'private-source';assert command(['git','rev-parse','HEAD'],cwd=source,capture=True)==CONFIG['products'][app]['commit']
 package=json.loads((source/'apps/desktop/package.json').read_text());assert package['sks']['id']==app and package['version']==CONFIG['version']
 return source
def source_view(source):
 command(['npm','ci','--no-audit','--no-fund'],cwd=source)
 return pathlib.Path(command(['node','--input-type=module','-e',"import {prepareSourceView} from './scripts/source-view.mjs'; console.log(prepareSourceView());"],cwd=source,capture=True))
def remove_owned(target):
 target=pathlib.Path(target).resolve();assert target.is_relative_to(TEMP.resolve()) and target!=TEMP.resolve()
 if target.is_dir():shutil.rmtree(target)
 elif target.exists():target.unlink()
def extract(archive,destination):
 destination.mkdir(parents=True,exist_ok=True);command(['tar','-xzf',archive,'-C',destination])

def native_minimum(desktop,app):
 # Installer compatibility must include the actual bundled Node/Python libraries,
 # not just Electron's lower deployment target. Inspect headers without executing them.
 magic={b'\xfe\xed\xfa\xce',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca'}
 binaries=[];seen=set();versions=[(12,0)]
 for root in [desktop/'resources/sks-agent',desktop/'resources/runtime']:
  for file in root.rglob('*'):
   if not file.is_file() or file.resolve() in seen:continue
   seen.add(file.resolve())
   with file.open('rb') as f:header=f.read(4)
   if header in magic:binaries.append(file)
 for offset in range(0,len(binaries),24):
  text=command(['otool','-l',*binaries[offset:offset+24]],capture=True);kind=None
  for line in text.splitlines():
   bits=line.split()
   if bits[:2]==['Load','command']:kind=None
   elif bits[:1]==['cmd'] and len(bits)>1:kind=bits[1]
   elif len(bits)==2 and ((kind=='LC_BUILD_VERSION' and bits[0]=='minos') or (kind=='LC_VERSION_MIN_MACOSX' and bits[0]=='version')):
    versions.append(tuple(int(part) for part in bits[1].split('.')))
 minimum='.'.join(str(part) for part in max(versions))
 receipt=TEMP/f'compatibility-{app}.json';receipt.write_text(json.dumps({'app':app,'minimumMacOS':minimum,'inspectedNativeBinaries':len(binaries),'sourceCommit':CONFIG['products'][app]['commit']}));upload(receipt)
 print('Bundled native runtime minimum macOS: '+minimum,flush=True)
 return minimum
def wait_native(app):
 required={f'native-{app}-{arch}.tar.gz' for arch in ['arm64','x64']}|{f'build-{app}-{arch}.json' for arch in ['arm64','x64']}|{f'renderer-{app}.tar.gz'}
 end=time.time()+1200
 while time.time()<end:
  release=json.loads(command(['gh','release','view',TAG,'-R',REPO,'--json','assets'],capture=True))
  available={a['name'] for a in release['assets'] if a['state']=='uploaded'}
  if required<=available:return
  time.sleep(20)
 raise RuntimeError('The matching native build payloads are not ready; no app test was started.')
def assemble():
 app=os.environ['PRODUCT'];source=source_root(app);view=source_view(source);desktop=view/'apps/desktop';cache=TEMP/'assembly';cache.mkdir(exist_ok=True);wait_native(app)
 for pattern in [f'native-{app}-*.tar.gz',f'build-{app}-*.json',f'renderer-{app}.tar.gz']:download(pattern,cache)
 for arch in ['arm64','x64']:
  archive=cache/f'native-{app}-{arch}.tar.gz';receipt=json.loads((cache/f'build-{app}-{arch}.json').read_text());assert receipt['sourceCommit']==CONFIG['products'][app]['commit'] and receipt['nativeSha256']==sha(archive)
  unpacked=TEMP/('native-'+arch);extract(archive,unpacked)
  for name in ['sks-agent','runtime']:
   dest=desktop/'resources'/name/arch;dest.parent.mkdir(parents=True,exist_ok=True);shutil.move(unpacked/name,dest)
  if (unpacked/'cluster').exists():shutil.copytree(unpacked/'cluster',desktop/'resources/cluster',dirs_exist_ok=True)
  remove_owned(unpacked);remove_owned(archive)
 extract(cache/f'renderer-{app}.tar.gz',desktop);remove_owned(cache/f'renderer-{app}.tar.gz')
 env={**os.environ,'GITHUB_WORKSPACE':str(view),'CSC_IDENTITY_AUTO_DISCOVERY':'false','CI':'true','SKS_MAC_MINIMUM_SYSTEM_VERSION':native_minimum(desktop,app)}
 print('Preparing copied Mac delivery media for '+app,flush=True)
 command(['node','apps/desktop/scripts/optimize-mac-media.mjs'],cwd=view,env=env)
 command(['node','apps/desktop/scripts/clean-ci-staging.mjs'],cwd=view,env=env)
 print('Assembling universal Mac app, DMG and update ZIP for '+app,flush=True)
 command(['node',ROOT/'ci/build-universal.cjs',desktop/'scripts/build-installer.cjs'],cwd=desktop,env=env)
 files=[]
 for suffix in ['.dmg','.zip','.blockmap','.yml']:
  files.extend((desktop/'release').glob('*'+suffix))
 assert any(f.name==f'SKS-{app.upper()}-0.1.19-universal.dmg' for f in files)
 assert any(f.name==f'SKS-{app.upper()}-0.1.19-universal.zip' for f in files)
 assert all(f.stat().st_size<2*1024**3 for f in files)
 for f in files:
  if f.name=='latest-mac.yml':
   copy=cache/f'latest-mac-{app}.yml';shutil.copyfile(f,copy);upload(copy)
  else:upload(f)
 print('Universal '+app+' packages staged privately for native verification.',flush=True)
def clock():
 folder=TEMP/'clock';folder.mkdir(exist_ok=True);file=folder/'verification-clock.json'
 result=subprocess.run(['gh','release','download',TAG,'-R',REPO,'--pattern',file.name,'--dir',folder],capture_output=True)
 if result.returncode:
  now=int(time.time()*1000);file.write_text(json.dumps({'startedAtMs':now,'deadlineMs':now+600000,'limitSeconds':600}));upload(file)
 value=json.loads(file.read_text());assert value['limitSeconds']==600
 with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('deadline='+str(value['deadlineMs'])+'\n')
 print('Using the original shared ten-minute native verification window.',flush=True)
def http(url,body=None):
 data=json.dumps(body).encode() if body else None
 request=urllib.request.Request(url,data=data,headers={'content-type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=2) as r:return r.status,json.loads(r.read())
 except urllib.error.HTTPError as e:
  raw=e.read();return e.code,json.loads(raw) if raw else {}
def verify():
 arch=os.environ['BUILD_ARCH'];expected='arm64' if arch=='arm64' else 'x86_64';assert os.uname().machine==expected
 deadline=int(os.environ['TEST_DEADLINE_MS'])/1000
 cache=TEMP/'verify';cache.mkdir(exist_ok=True)
 download('SKS-*-0.1.19-universal.zip',cache)
 tools=TEMP/'verify-tools';command(['npm','install','--prefix',tools,'--no-audit','--no-fund','--ignore-scripts','@electron/asar@4.0.1'])
 for app in ['lab','designz','proz']:
  archive=cache/f'SKS-{app.upper()}-0.1.19-universal.zip';archive_hash=sha(archive);proof=cache/f'proof-{app}-{arch}.json'
  previous=subprocess.run(['gh','release','download',TAG,'-R',REPO,'--pattern',proof.name,'--dir',cache,'--clobber'],capture_output=True)
  if previous.returncode==0:
   value=json.loads(proof.read_text())
   if value.get('ok') and value.get('archiveSha256')==archive_hash and value.get('sourceCommit')==CONFIG['products'][app]['commit']:
    print('Reused passed native verification for '+app+' '+arch,flush=True);continue
  if time.time()>=deadline-10:raise RuntimeError('Shared ten-minute test budget exhausted; no further app tests started.')
  unpacked=TEMP/('verify-'+app);unpacked.mkdir(exist_ok=True);command(['ditto','-x','-k',archive,unpacked])
  bundle=next(unpacked.glob('*.app'));info=plistlib.load((bundle/'Contents/Info.plist').open('rb'));assert info['CFBundleShortVersionString']=='0.1.19'
  binary=bundle/'Contents/MacOS'/info['CFBundleExecutable'];command(['lipo','-verify_arch','x86_64','arm64',binary]);command(['codesign','--verify','--deep','--strict',bundle])
  asar=bundle/'Contents/Resources/app.asar'
  js="const {createRequire}=require('node:module'); const a=createRequire(process.argv[1])('@electron/asar'); console.log(a.extractFile(process.argv[2],'package.json').toString());"
  manifest=json.loads(command(['node','-e',js,tools/'package.json',asar],capture=True));assert manifest['sks']['id']==app and manifest['version']=='0.1.19'
  flags=manifest['sks']['features'];assert all(flags[x] is (app=='lab') for x in ['company','social','deepResearch'])
  state=TEMP/('isolated-'+app);state.mkdir(exist_ok=True);debug_port=19300
  env={**os.environ,'HOME':str(state),'SKS_HOME':str(state/'agent-home'),'SKS_APP_ID':app};env.pop('ELECTRON_RUN_AS_NODE',None)
  with LOG.open('a') as log:
   child=subprocess.Popen([str(binary),'--no-first-run','--remote-debugging-port='+str(debug_port),'--enable-logging=stderr'],env=env,stdout=log,stderr=log,start_new_session=True)
   try:
    ports={'lab':range(8765,8785),'designz':range(8851,8861),'proz':range(8861,8871)}[app]
    ready=None;start=time.time();end=min(deadline-3,start+100)
    while time.time()<end:
     if child.poll() is not None:raise RuntimeError(app+' native Mac app exited before startup.')
     for port in ports:
      try:
       status,health=http('http://127.0.0.1:'+str(port)+'/health')
       if status==200 and health.get('ok') and health.get('appId')==app:ready=(port,health);break
      except Exception:pass
     if ready:break
     time.sleep(.3)
    if not ready:raise RuntimeError(app+' native Mac agent did not become ready within the shared deadline.')
    port,health=ready;assert health.get('authRequired') is True
    status,denied=http('http://127.0.0.1:'+str(port)+'/desk',{'action':'state'});assert status==401 and denied.get('code')=='signin_required'
    status,identity=http('http://127.0.0.1:'+str(port)+'/desk',{'action':'account.auth.status'});assert status==200 and identity['centralAccount']['status']=='signed_out' and identity['centralAccount']['app']['id']==app
    page_ready=False
    while time.time()<min(deadline-3,start+100):
     try:
      status,pages=http('http://127.0.0.1:'+str(debug_port)+'/json/list')
      if status==200 and any(p.get('type')=='page' and '/renderer/' in p.get('url','') and 'index.html' in p.get('url','') for p in pages):page_ready=True;break
     except Exception:pass
     time.sleep(.3)
    assert page_ready,'Packaged renderer did not load.'
    assert time.time()<=deadline
    result={'ok':True,'app':app,'arch':arch,'machine':os.uname().machine,'macOS':command(['sw_vers','-productVersion'],capture=True),'sourceCommit':CONFIG['products'][app]['commit'],'version':'0.1.19','archiveSha256':archive_hash,'universalShell':True,'signatureValid':True,'packagedAppStarted':True,'rendererLoaded':True,'nativeAgentReady':True,'productIdentity':app,'protectedDeskDeniedUnsigned':True,'signedOutAdapterReady':True,'featureAvailabilityCorrect':True,'testedAtMs':int(time.time()*1000),'deadlineMs':int(deadline*1000),'screenControlUsed':False}
    proof.write_text(json.dumps(result,indent=2));upload(proof);print('Passed native Mac '+app+' '+arch,flush=True)
   finally:
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:child.wait(timeout=3)
    except subprocess.TimeoutExpired:
     try:os.killpg(child.pid,signal.SIGKILL)
     except ProcessLookupError:pass
  remove_owned(unpacked)
def publish():
 app=os.environ['PRODUCT'];source=source_root(app);out=TEMP/'publish';out.mkdir(exist_ok=True)
 download(f'proof-{app}-*.json',out)
 verified_hashes=set()
 for arch in ['arm64','x64']:
  proof=json.loads((out/f'proof-{app}-{arch}.json').read_text());assert proof['ok'] and proof['sourceCommit']==CONFIG['products'][app]['commit'] and proof['testedAtMs']<=proof['deadlineMs']
  verified_hashes.add(proof['archiveSha256'])
 for pattern in [f'SKS-{app.upper()}-0.1.19-universal.*',f'latest-mac-{app}.yml']:download(pattern,out)
 shutil.copyfile(out/f'latest-mac-{app}.yml',out/'latest-mac.yml')
 assert verified_hashes=={sha(out/f'SKS-{app.upper()}-0.1.19-universal.zip')}
 print('Publishing verified Mac '+app+' installer and update channel.',flush=True)
 command(['node',source/'apps/desktop/scripts/publish-release.mjs','--platform=mac','--directory='+str(out)],cwd=source)
 receipt={'app':app,'version':'0.1.19','sourceCommit':CONFIG['products'][app]['commit'],'platform':'mac','nativeArchitectures':['arm64','x64'],'files':[]}
 for suffix in ['dmg','zip']:
  file=out/f'SKS-{app.upper()}-0.1.19-universal.{suffix}';receipt['files'].append({'name':file.name,'size':file.stat().st_size,'sha256':sha(file)})
 receipt_file=out/f'publication-{app}-mac.json';receipt_file.write_text(json.dumps(receipt,indent=2));upload(receipt_file);print('Published Mac '+app+' 0.1.19.',flush=True)
try:{'assemble':assemble,'clock':clock,'verify':verify,'publish':publish}[sys.argv[1]]()
except Exception as error:
 print(str(error) or type(error).__name__,file=sys.stderr,flush=True)
 if LOG.exists():
  try:upload(LOG)
  except Exception:pass
 sys.exit(1)
