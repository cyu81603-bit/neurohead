"""Restore the frozen speech model from the verified full GitHub Release ZIP."""
import argparse,hashlib,os,shutil,tempfile,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE_SHA='e5e00c42d881cf15281d725ff60515caabe547db7f8e3a42c65d194c495670f3'
MODEL_SHA='c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'
MODEL='integration/embodied/models/sensevoice_small_int8/model.int8.onnx'
MEMBER='neurohead_r6_7_final_20261101/'+MODEL
URL='https://github.com/cyu81603-bit/neurohead/releases/download/r6.7-final-20261101/neurohead_r6_7_final_20261101.zip'
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def restore(archive,destination):
 if digest(archive)!=ARCHIVE_SHA:raise ValueError('Full archive SHA256 mismatch; no project files changed')
 destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile(prefix='model-',suffix='.tmp',dir=destination.parent,delete=False) as f:
  staged=Path(f.name)
 try:
  with zipfile.ZipFile(archive) as z,z.open(MEMBER) as src,staged.open('wb') as out:shutil.copyfileobj(src,out)
  if digest(staged)!=MODEL_SHA:raise ValueError('Model SHA256 mismatch')
  os.replace(staged,destination)
 finally:
  if staged.exists():staged.unlink()
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',type=Path);args=parser.parse_args();destination=ROOT/'project'/MODEL
 if destination.exists():
  if digest(destination)!=MODEL_SHA:raise SystemExit('Existing model differs; move it aside before restoring')
  print('MODEL_HASH_PASS; model already present');return
 if args.archive:restore(args.archive,destination)
 else:
  cache=ROOT/'.release_cache';cache.mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir=cache,prefix='restore-') as tmp:
   archive=Path(tmp)/'full.zip';print('Downloading verified full release ZIP...',flush=True)
   req=urllib.request.Request(URL,headers={'User-Agent':'NeuroHead-model-restore'})
   with urllib.request.urlopen(req,timeout=60) as src,archive.open('wb') as out:shutil.copyfileobj(src,out)
   restore(archive,destination)
 print('MODEL_HASH_PASS',destination)
if __name__=='__main__':main()
