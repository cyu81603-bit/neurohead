"""Portable, read-only verification of a previously trusted SHA256 manifest."""
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inventory(root):
    root = Path(root).resolve()
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink not supported: ' + str(path))
        if path.is_file():
            if root not in path.resolve().parents:
                raise ValueError('outside root')
            files[path.relative_to(root).as_posix()] = digest(path)
    return files


def create(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if root == output or root in output.parents:
        raise ValueError('manifest output must be outside scanned root')
    if output.exists():
        raise FileExistsError('refuse to overwrite trusted manifest')
    files = inventory(root)
    if not files:
        raise ValueError('empty inventory')
    output.write_text(json.dumps(dict(schema_version=1, files=files), indent=2), encoding='utf-8')
    return len(files)


def verify(root, manifest, strict=False):
    root = Path(root).resolve()
    data = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    files = data.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('nonempty files mapping required')
    seen = set()
    for name, wanted in files.items():
        if not isinstance(name, str) or '\\' in name or ':' in name:
            raise ValueError('use portable relative POSIX paths')
        relative = Path(name)
        parts = name.split('/')
        if relative.is_absolute() or PureWindowsPath(name).is_absolute() or any(p in ('', '.', '..') for p in parts):
            raise ValueError('unsafe relative path')
        if name.casefold() in seen:
            raise ValueError('case alias in manifest')
        seen.add(name.casefold())
        path = root / relative
        if root not in path.resolve().parents or not path.is_file():
            raise ValueError('missing/outside root: ' + name)
        if any(p.is_symlink() for p in [path] + list(path.parents) if p != root and root in p.parents):
            raise ValueError('symlink in path')
        if not isinstance(wanted, str) or not re.fullmatch('[0-9a-f]{64}', wanted):
            raise ValueError('invalid SHA256')
        if digest(path) != wanted:
            raise ValueError('hash mismatch: ' + name)
    extras = sorted(set(inventory(root)) - set(files))
    if strict and extras:
        raise ValueError('unlisted files: ' + ', '.join(extras))
    return dict(verified_files=len(files), unlisted_files=extras, authenticated=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['create', 'verify'])
    p.add_argument('root')
    p.add_argument('manifest')
    p.add_argument('--strict', action='store_true')
    a = p.parse_args()
    print(json.dumps(create(a.root, a.manifest) if a.mode == 'create' else verify(a.root, a.manifest, a.strict), indent=2))
