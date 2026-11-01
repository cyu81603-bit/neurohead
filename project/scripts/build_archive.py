"""Archive the submission root, generate hashes, then verify every ZIP member."""
import argparse,hashlib,json,zipfile,re
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--output',type=Path,default=R.parent/(R.name+'.zip'));x=a.parse_args();archive=x.output.resolve()
 if R in archive.parents or archive.exists():raise SystemExit('Destination must be new and outside source')
 paths=sorted(p for p in R.rglob('*') if p.is_file())
 for p in paths:
  if '__pycache__' in p.parts or not all(re.fullmatch('[A-Za-z0-9_.-]+',v) for v in p.relative_to(R).parts):raise ValueError('Invalid package path: '+str(p))
 files={p.relative_to(R).as_posix():digest(p) for p in paths if p.name!='manifest.json' or p.parent!=R}
 (R/'manifest.json').write_text(json.dumps(dict(version='r6.7',files=files),indent=2),encoding='utf-8')
 paths=sorted(p for p in R.rglob('*') if p.is_file())
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in paths:z.write(p,R.name+'/'+p.relative_to(R).as_posix())
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None
  for name,want in files.items():
   h=hashlib.sha256()
   with z.open(R.name+'/'+name) as f:
    for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
   assert h.hexdigest()==want,name
 result=dict(version='r6.7',archive=str(archive),files=len(paths),bytes=archive.stat().st_size,sha256=digest(archive),all_member_hashes_verified=True,technical_report_included=False)
 archive.with_suffix('.sha256').write_text(result['sha256']+'  '+archive.name+'\n',encoding='utf-8')
 archive.with_suffix('.verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
