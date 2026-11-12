import hashlib,json,os,pathlib,re,shutil,subprocess,sys,time

ROOT=pathlib.Path(__file__).resolve().parent.parent
CONFIG=json.loads((ROOT/os.environ.get('RELEASE_CONFIG','ci/release-0120.json')).read_text(encoding='utf-8-sig'))
VERSION=CONFIG['version'];SERIES=VERSION.replace('.','')
TEMP=pathlib.Path(os.environ['RUNNER_TEMP']);REPO='steelx888-afk/SKS-Downloads'
TAG=os.environ['CACHE_TAG'];APP=os.environ['PRODUCT'];PLATFORM=os.environ['BUILD_PLATFORM']
SOURCE=ROOT/'private-source';LOG=TEMP/f'desktop-{APP}-{PLATFORM}.log'

def command(args,cwd=None,env=None,capture=False):
 with LOG.open('a',encoding='utf-8') as log:
  result=subprocess.run([str(a) for a in args],cwd=cwd,env=env,text=True,stdout=subprocess.PIPE if capture else log,stderr=log)
 if result.returncode:raise RuntimeError('Release command failed: '+pathlib.Path(str(args[0])).name+' (private log retained)')
 return result.stdout.strip() if capture else None

def sha(file):
 with pathlib.Path(file).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def restore_media():
 archive=TEMP/f'public-media-{SERIES}.tar.gz'
 command(['gh','release','download',TAG,'-R',REPO,'--pattern',archive.name,'--dir',TEMP])
 media=TEMP/'public-media';media.mkdir(exist_ok=True);command(['tar','-xzf',archive,'-C',media])
 restored=0
 for target in (SOURCE/'apps/web/public').rglob('*'):
  if not target.is_file() or target.stat().st_size>2048:continue
  raw=target.read_bytes()
  if not raw.startswith(b'version https://git-lfs.github.com/spec/v1'):continue
  oid=re.search(rb'oid sha256:([0-9a-f]{64})',raw).group(1).decode();expected=int(re.search(rb'size (\d+)',raw).group(1))
  source=media/target.relative_to(SOURCE/'apps/web/public')
  assert source.is_file() and source.stat().st_size==expected and sha(source)==oid
  shutil.copyfile(source,target);restored+=1
 print(f'Restored {restored} exact public media objects.',flush=True)

def main():
 assert TAG.startswith(f'mac-native-cache-{SERIES}-')
 actual=command(['git','rev-parse','HEAD'],cwd=SOURCE,capture=True);assert actual==CONFIG['products'][APP]['commit']
 package=json.loads((SOURCE/'apps/desktop/package.json').read_text());assert package['version']==VERSION and package['sks']['id']==APP
 command(['npm','ci','--no-audit','--no-fund'],cwd=SOURCE)
 restore_media()
 view=pathlib.Path(command(['node','--input-type=module','-e',"import {prepareSourceView} from './scripts/source-view.mjs'; console.log(prepareSourceView());"],cwd=SOURCE,capture=True))
 env={**os.environ,'CI':'true','CSC_IDENTITY_AUTO_DISCOVERY':'false','NODE_OPTIONS':'--max-old-space-size=4096','PYTHONUNBUFFERED':'1','PIP_NO_CACHE_DIR':'1'}
 command(['node','apps/desktop/scripts/pack-app.mjs'],cwd=view,env=env)
 command(['node','apps/desktop/scripts/clean-ci-staging.mjs'],cwd=view,env=env)
 desktop=view/'apps/desktop'
 command(['node','scripts/smoke-agent.mjs'],cwd=desktop,env=env)
 if PLATFORM=='windows':
  command(['node','scripts/build-installer.cjs'],cwd=desktop,env=env)
  command(['node','scripts/smoke-installer-payload.mjs'],cwd=desktop,env=env)
 else:
  command(['npx','electron-builder','--linux','AppImage','--x64','--publish','never'],cwd=desktop,env=env)
 command(['node','scripts/publish-release.mjs',f'--platform={PLATFORM}'],cwd=desktop,env={**env,'GH_TOKEN':os.environ['GH_TOKEN']})
 release=desktop/'release';prefix=f'SKS-{APP.upper()}'
 binary=release/(f'{prefix}-Setup-{VERSION}-x64.exe' if PLATFORM=='windows' else f'{prefix}-{VERSION}-x64.AppImage')
 receipt={'app':APP,'platform':PLATFORM,'version':VERSION,'sourceCommit':actual,'file':binary.name,'size':binary.stat().st_size,'sha256':sha(binary),'screenControlUsed':False}
 receipt_file=TEMP/f'publication-{APP}-{PLATFORM}.json';receipt_file.write_text(json.dumps(receipt,indent=2))
 command(['gh','release','upload',TAG,'-R',REPO,'--clobber',receipt_file])
 print(f'Published {APP} {VERSION} for {PLATFORM}.',flush=True)

try:main()
except Exception as error:
 print(str(error) or type(error).__name__,file=sys.stderr,flush=True)
 if LOG.exists():
  subprocess.run(['gh','release','upload',TAG,'-R',REPO,'--clobber',str(LOG)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 sys.exit(1)
