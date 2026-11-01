"""Offline asset inspection; PYNQ is imported only for explicit loading."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inspect_bundle(bitfile, expected_ips=(), manifest=None):
    bit = Path(bitfile).resolve()
    if bit.suffix.lower() != '.bit':
        raise ValueError('only full .bit overlays supported')
    hwh = bit.with_suffix('.hwh')
    for path in (bit, hwh):
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('missing/empty asset: ' + str(path))
    hashes = {p.name: sha256(p) for p in (bit, hwh)}
    if manifest is not None:
        data = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
        wanted = data.get('files', {})
        for name, value in hashes.items():
            if wanted.get(name) != value:
                raise ValueError('trusted hash mismatch/missing: ' + name)
    tree = ET.parse(hwh)
    modules = {}
    for node in tree.iter():
        if node.tag.rsplit('}', 1)[-1] == 'MODULE':
            path = node.get('FULLNAME', '').strip('/')
            if path:
                modules[path] = node.get('VLNV', '')
    missing = set(expected_ips) - set(modules)
    if missing:
        raise ValueError('HWH missing expected IP: ' + ', '.join(sorted(missing)))
    return dict(bitfile=str(bit), hwh=str(hwh), sha256=hashes,
                trusted_hashes_verified=manifest is not None, hwh_modules=modules,
                scope='offline metadata only; no physical verification')


def load_overlay(bitfile, expected_ips, manifest=None, overlay_factory=None):
    expected_ips = tuple(expected_ips)
    if not expected_ips:
        raise ValueError('specify at least one expected IP')
    report = inspect_bundle(bitfile, expected_ips, manifest)
    if manifest is None:
        raise ValueError('loading requires a trusted hash manifest')
    if overlay_factory is None:
        from pynq import Overlay
        overlay_factory = Overlay
    overlay = overlay_factory(report['bitfile'], download=False)
    if set(expected_ips) - set(overlay.ip_dict):
        raise ValueError('PYNQ ip_dict does not contain expected IPs')
    report['ip_dict'] = {name: {k: overlay.ip_dict[name].get(k)
                               for k in ('phys_addr', 'addr_range', 'type')}
                         for name in expected_ips}
    overlay.download()
    if not overlay.is_loaded():
        raise RuntimeError('overlay not reported loaded')
    report.update(loaded=True, hardware_identity_verified=False)
    return overlay, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bitfile')
    parser.add_argument('--ip', action='append', default=[])
    parser.add_argument('--manifest')
    args = parser.parse_args()
    print(json.dumps(inspect_bundle(args.bitfile, args.ip, args.manifest), indent=2))
