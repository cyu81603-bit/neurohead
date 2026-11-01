"""Verify all package files except the manifest itself; no external dependencies."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('manifest_helper', ROOT/'skill/fpga-evidence/scripts/manifest.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if __name__ == '__main__':
    result = module.verify(ROOT, ROOT/'manifest.json')
    extras = set(result['unlisted_files']) - {'manifest.json'}
    if extras:
        raise SystemExit('unexpected files: ' + ', '.join(sorted(extras)))
    print('PACKAGE_HASH_PASS', result['verified_files'])
