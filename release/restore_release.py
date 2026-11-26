"""Reconstruct an already-tested payload; verify exact bytes before uploading a draft asset."""
import os,re,subprocess,json,hashlib,sys
from pathlib import Path
p=os.environ['PRODUCT'];base=os.environ['BASE_VERSION'];version=os.environ['VERSION'];expected=os.environ['DELTA_SHA256']
assert p in {'lab','proz','designz'}
assert all(re.fullmatch(r'\d+\.\d+\.\d+',v) for v in [base,version])
assert re.fullmatch('[a-f0-9]{64}',expected)
repo=os.environ['GITHUB_REPOSITORY'];base_tag=f'{p}-{base}';tag=f'{p}-{version}'
def gh(*args):return subprocess.check_output(['gh',*args,'--repo',repo],text=True).strip()
release=json.loads(gh('release','view',tag,'--json','isDraft'));assert release['isDraft']
Path('transfer').mkdir(exist_ok=True)
gh('release','download',base_tag,'--pattern',f'sks-{p}-{base}-windows-x64.zip','--dir','transfer')
gh('release','download',tag,'--pattern','release-delta.zip','--dir','transfer')
patch=Path('transfer/release-delta.zip');assert hashlib.file_digest(patch.open('rb'),'sha256').hexdigest()==expected
output=Path('transfer')/f'sks-{p}-{version}-windows-x64.zip'
subprocess.run([sys.executable,'release/apply_delta.py',f'transfer/sks-{p}-{base}-windows-x64.zip',str(patch),str(output),str(Path('delta-tools').resolve())],check=True)
gh('release','upload',tag,str(output))
asset=next(a for a in json.loads(gh('release','view',tag,'--json','assets'))['assets'] if a['name']==output.name)
assert asset['size']==output.stat().st_size
gh('release','delete-asset',tag,'release-delta.zip','--yes')
