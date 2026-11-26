import sys,zipfile,json,hashlib,zlib
from pathlib import Path
sys.path.insert(0,sys.argv[4]);import bsdiff4
base,patch,output=map(Path,sys.argv[1:4])
with zipfile.ZipFile(patch) as delta:
 plan=json.loads(delta.read('plan.json'))
 assert hashlib.file_digest(base.open('rb'),'sha256').hexdigest()==plan['baseSha256']
 assert zlib.ZLIB_RUNTIME_VERSION==plan['zlib'],(zlib.ZLIB_RUNTIME_VERSION,plan['zlib'])
 with base.open('rb') as source,output.open('wb') as target:
  for item in plan['segments']:
   if 'rebuild' in item:
    source.seek(item['copy']);old=zlib.decompress(source.read(item['size']),-15)
    raw=bsdiff4.patch(old,delta.read(item['rebuild']));compress=zlib.compressobj(1,zlib.DEFLATED,-15);data=compress.compress(raw)+compress.flush()
    assert hashlib.sha256(data).hexdigest()==item['sha256'];target.write(data)
   elif 'copy' in item:
    source.seek(item['copy']);remaining=item['size']
    while remaining:
     data=source.read(min(remaining,4*1024*1024));assert data;target.write(data);remaining-=len(data)
   else:target.write(delta.read(item['literal']))
 assert output.stat().st_size==plan['size']
 assert hashlib.file_digest(output.open('rb'),'sha256').hexdigest()==plan['sha256']
 print(json.dumps({'product':plan['product'],'sha256':plan['sha256'],'size':plan['size'],'verified':True}))
