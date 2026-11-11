import os,sys,json,pathlib,subprocess,hashlib,shutil,tarfile,re,time
ROOT=pathlib.Path(__file__).resolve().parent.parent
CONFIG=json.loads((ROOT/'ci/mac-release-019.json').read_text(encoding='utf-8-sig'))
TEMP=pathlib.Path(os.environ['RUNNER_TEMP'])
REPO='steelx888-afk/SKS-Downloads'
TAG=os.environ.get('CACHE_TAG') or 'mac-native-cache-019-'+os.environ['GITHUB_RUN_ID']
LOG=TEMP/('mac-build-'+os.environ.get('PRODUCT','prepare')+'-'+os.environ.get('BUILD_ARCH','any')+'.log')
def command(args,cwd=None,env=None,capture=False):
 result=subprocess.run([str(a) for a in args],cwd=cwd,env=env,text=True,stdout=subprocess.PIPE if capture else LOG.open('a'),stderr=LOG.open('a'))
 if result.returncode:raise RuntimeError('Build command failed: '+pathlib.Path(str(args[0])).name+' (private log retained)')
 return result.stdout.strip() if capture else None
def upload(*files):command(['gh','release','upload',TAG,'-R',REPO,'--clobber',*files])
def extract(archive,destination):
 destination.mkdir(parents=True,exist_ok=True)
 command(['tar','-xzf',archive,'-C',destination])
def remove_owned(target):
 target=pathlib.Path(target).resolve()
 assert target.is_relative_to(TEMP.resolve()) and target!=TEMP.resolve()
 if target.is_dir():shutil.rmtree(target)
 elif target.exists():target.unlink()
def prepare():
 command(['gh','release','create',TAG,'-R',REPO,'--draft','--target',os.environ['GITHUB_SHA'],'--title','Temporary private Mac build cache 0.1.19','--notes','Compiled build staging only. Deleted after verified publication.'])
 out=TEMP/'mac-cache';out.mkdir(exist_ok=True)
 command(['gh','release','download','lab-latest','-R',REPO,'--pattern','SKS-LAB-0.1.19-x64.AppImage','--dir',out])
 binary=out/'SKS-LAB-0.1.19-x64.AppImage'
 release=json.loads(command(['gh','api','repos/'+REPO+'/releases/tags/lab-latest'],capture=True))
 asset=next(a for a in release['assets'] if a['name']==binary.name)
 h=hashlib.file_digest(binary.open('rb'),'sha256').hexdigest();assert asset['digest']=='sha256:'+h
 binary.chmod(0o755);command([binary,'--appimage-extract'],cwd=out)
 asars=list((out/'squashfs-root').rglob('app.asar'));assert len(asars)==1
 tools=TEMP/'asar-tools';command(['npm','install','--prefix',tools,'--ignore-scripts','--no-audit','--no-fund','@electron/asar@4.0.1'])
 media=TEMP/'published-media';media.mkdir(exist_ok=True)
 command(['node',ROOT/'ci/extract-public-media.cjs',asars[0],media],env={**os.environ,'ASAR_MODULE':str(tools/'node_modules/@electron/asar')})
 archive=TEMP/'public-media-019.tar.gz';command(['tar','-czf',archive,'-C',media,'.']);assert archive.stat().st_size<2*1024**3
 upload(archive)
 with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('cache_tag='+TAG+'\n')
 print('Prepared shared media cache from verified, published installer.',flush=True)
def native():
 app=os.environ['PRODUCT'];arch=os.environ['BUILD_ARCH'];source=ROOT/'private-source'
 actual=command(['git','rev-parse','HEAD'],cwd=source,capture=True);assert actual==CONFIG['products'][app]['commit']
 package=json.loads((source/'apps/desktop/package.json').read_text());assert package['version']==CONFIG['version'] and package['sks']['id']==app
 print('Installing locked build dependencies for '+app+' '+arch,flush=True)
 command(['npm','ci','--no-audit','--no-fund'],cwd=source)
 archive=TEMP/'public-media-019.tar.gz';command(['gh','release','download',TAG,'-R',REPO,'--pattern',archive.name,'--dir',TEMP])
 media=TEMP/'media';extract(archive,media)
 restored=0
 for p in (source/'apps/web/public').rglob('*'):
  if not p.is_file() or p.stat().st_size>2048:continue
  raw=p.read_bytes()
  if not raw.startswith(b'version https://git-lfs.github.com/spec/v1'):continue
  oid=re.search(rb'oid sha256:([0-9a-f]{64})',raw).group(1).decode();expected=int(re.search(rb'size (\d+)',raw).group(1))
  candidate=media/p.relative_to(source/'apps/web/public');assert candidate.is_file(),str(p.relative_to(source))
  assert candidate.stat().st_size==expected and hashlib.file_digest(candidate.open('rb'),'sha256').hexdigest()==oid
  shutil.copyfile(candidate,p);restored+=1
 remove_owned(media);remove_owned(archive)
 print('Restored '+str(restored)+' exact public source media objects without private LFS billing.',flush=True)
 view=pathlib.Path(command(['node','--input-type=module','-e',"import {prepareSourceView} from './scripts/source-view.mjs'; console.log(prepareSourceView());"],cwd=source,capture=True))
 print('Building native '+app+' '+arch+' payload.',flush=True)
 command(['node','apps/desktop/scripts/pack-app.mjs'],cwd=view,env={**os.environ,'PYTHONUNBUFFERED':'1','PIP_NO_CACHE_DIR':'1','NODE_OPTIONS':'--max-old-space-size=4096'})
 desktop=view/'apps/desktop';out=TEMP/'native-out';out.mkdir(exist_ok=True)
 native_archive=out/f'native-{app}-{arch}.tar.gz';command(['tar','-czf',native_archive,'-C',desktop/'resources','sks-agent','runtime','cluster'])
 assert native_archive.stat().st_size<2*1024**3;upload(native_archive)
 if arch=='arm64':
  renderer=out/f'renderer-{app}.tar.gz';command(['tar','-czf',renderer,'-C',desktop,'renderer','dist','assets']);assert renderer.stat().st_size<2*1024**3;upload(renderer)
 receipt={'app':app,'arch':arch,'sourceCommit':actual,'version':package['version'],'nativePayload':native_archive.name,'nativeSha256':hashlib.file_digest(native_archive.open('rb'),'sha256').hexdigest()}
 receipt_file=out/f'build-{app}-{arch}.json';receipt_file.write_text(json.dumps(receipt,indent=2));upload(receipt_file)
 print('Built and staged '+app+' '+arch+' native payload; application testing has not started.',flush=True)
try:
 {'prepare':prepare,'native':native}[sys.argv[1]]()
except Exception as error:
 print(str(error),file=sys.stderr,flush=True)
 if LOG.exists():
  try:upload(LOG)
  except Exception:pass
 sys.exit(1)
