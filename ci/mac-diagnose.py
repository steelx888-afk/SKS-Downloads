import os,json,pathlib,subprocess,time,signal,plistlib,urllib.request,urllib.error
import importlib.util
root=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('mac_finish',root/'mac-finish.py')
# Use the existing staged package; do not build or re-run signature checks.
temp=pathlib.Path(os.environ['RUNNER_TEMP']);repo='steelx888-afk/SKS-Downloads';tag=os.environ['CACHE_TAG']
out=temp/'diagnose';out.mkdir(exist_ok=True)
def gh(*args):return subprocess.check_output(['gh',*args],text=True)
def upload(file):gh('release','upload',tag,'-R',repo,'--clobber',str(file))
gh('release','download',tag,'-R',repo,'--pattern','SKS-LAB-0.1.19-universal.zip','--dir',str(out))
subprocess.run(['ditto','-x','-k',str(out/'SKS-LAB-0.1.19-universal.zip'),str(out)],check=True)
bundle=next(out.glob('*.app'));info=plistlib.load((bundle/'Contents/Info.plist').open('rb'));binary=bundle/'Contents/MacOS'/info['CFBundleExecutable']
clock=out/'diagnostic-clock.json'
old=subprocess.run(['gh','release','download',tag,'-R',repo,'--pattern',clock.name,'--dir',str(out)],capture_output=True)
if old.returncode:
 now=int(time.time()*1000);clock.write_text(json.dumps({'startedAtMs':now,'deadlineMs':now+600000,'limitSeconds':600,'authorization':'Allow one additional 10-minute window','purpose':'Capture packaged-agent startup logs, repair and verify failed/unreached cases'}));upload(clock)
deadline=json.loads(clock.read_text())['deadlineMs']/1000
assert time.time()<deadline
state=temp/'diagnostic-state';state.mkdir(exist_ok=True);log=temp/'mac-startup-diagnostic.log'
env={**os.environ,'HOME':str(state),'SKS_HOME':str(state/'agent-home')}
for key in ['NODE_OPTIONS','ELECTRON_RUN_AS_NODE','GH_TOKEN','GITHUB_TOKEN']:env.pop(key,None)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(url):
 try:
  with opener.open(url,timeout=.4) as r:return {'status':r.status,'body':json.loads(r.read())}
 except Exception as e:return {'error':type(e).__name__+': '+str(e)}
with log.open('w') as stream:
 child=subprocess.Popen([str(binary),'--no-first-run','--remote-debugging-port=19300','--enable-logging=stderr'],env=env,stdout=stream,stderr=stream,cwd=out,start_new_session=True)
 try:
  end=min(deadline-5,time.time()+25)
  while time.time()<end and child.poll() is None:time.sleep(1)
  records={'machine':os.uname().machine,'childExit':child.poll(),'health':{str(p):get('http://127.0.0.1:'+str(p)+'/health') for p in range(8765,8775)},'pages':get('http://127.0.0.1:19300/json/list'),'proxyEnvironmentNames':[key for key in os.environ if 'proxy' in key.lower()]}
  (out/'mac-startup-diagnostic.json').write_text(json.dumps(records,indent=2))
  for parent in [state/'Library/Application Support',pathlib.Path.home()/'Library/Application Support']:
   if not parent.exists():continue
   for file in parent.rglob('agent.log'):
    if file.is_file():
     with log.open('a') as f:f.write('\nAGENT LOG '+str(file)+'\n'+file.read_text(errors='replace')[-24000:]+'\n')
   for file in parent.rglob('screen.log'):
    if file.is_file():
     with log.open('a') as f:f.write('\nSCREEN LOG '+str(file)+'\n'+file.read_text(errors='replace')[-12000:]+'\n')
 finally:
  try:os.killpg(child.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:child.wait(timeout=3)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL)
upload(log);upload(out/'mac-startup-diagnostic.json')
print('Captured packaged startup and agent logs in the private draft. No rebuild, model calls or screen control.')
