"""Audit evidence claims offline. This never controls hardware or proves source authenticity."""
import argparse
import json
import math
from pathlib import Path
import re
import time


def audit(data, now=None):
    now = time.time() if now is None else now
    mode = data.get('mode')
    if mode not in ('simulation', 'hardware'):
        raise ValueError('explicit evidence mode required')
    captured, ttl = data.get('captured_at_epoch'), data.get('max_age_seconds')
    for value in (now, captured, ttl):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('finite evidence timestamps/age required')
    if ttl <= 0 or captured > now or now - captured > ttl:
        raise ValueError('stale/future evidence')
    build = data.get('build_id')
    if not isinstance(build, str) or not build or build != data.get('current_build_id'):
        raise ValueError('build identity changed/missing')
    profile = data.get('profile_sha256', '')
    if not isinstance(profile, str) or not re.fullmatch('[0-9a-f]{64}', profile) or profile != data.get('current_profile_sha256'):
        raise ValueError('profile changed/missing')
    evidence = data.get('evidence', {})
    if not isinstance(evidence, dict):
        raise ValueError('evidence mapping required')
    def available(name):
        entry = evidence.get(name, {})
        return (isinstance(entry, dict) and entry.get('verified') is True
                and isinstance(entry.get('source'), str) and bool(entry['source'].strip()))
    verified = {
        'digital_verified': available('digital'),
        'waveform_verified': mode == 'hardware' and available('waveform'),
        'physical_motion_verified': mode == 'hardware' and available('physical_motion'),
        'closed_loop_error_measured': mode == 'hardware' and available('physical_motion') and available('closed_loop_sensor')
    }
    claims = data.get('claims')
    if not isinstance(claims, list) or not all(isinstance(c, str) and c in verified for c in claims):
        raise ValueError('known claims list required')
    unsupported = [c for c in claims if not verified[c]]
    return dict(claims_consistent=not unsupported, unsupported_claims=unsupported,
                evidence_levels=verified, mode=mode, build_id=build,
                physical_acceptance='not inferred from digital status',
                authenticity='not checked; supplied evidence metadata only')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trial')
    p.add_argument('--now', type=float, help='deterministic offline replay only')
    a = p.parse_args()
    result = audit(json.loads(Path(a.trial).read_text(encoding='utf-8-sig')), a.now)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['claims_consistent'] else 1)
