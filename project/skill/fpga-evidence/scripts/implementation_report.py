"""Parse supported Vivado text reports; unknown format fails, never fills zero."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def parse(directory):
    root = Path(directory)
    timing = root / 'timing_summary.rpt'
    utilization = root / 'utilization.rpt'
    t = timing.read_text(encoding='utf-8-sig', errors='replace')
    u = utilization.read_text(encoding='utf-8-sig', errors='replace')
    def header(text, field):
        m = re.search(r'^\|\s*' + re.escape(field) + r'\s*:\s*(.+)$', text, re.M)
        if not m:
            raise ValueError('missing report header: ' + field)
        return m[1].strip()
    identities = {k: header(t, k) for k in ('Tool Version', 'Design', 'Device', 'Design State')}
    if identities['Design State'].lower() != 'routed':
        raise ValueError('timing report is not Routed')
    for key in ('Tool Version', 'Design'):
        if header(u, key) != identities[key]:
            raise ValueError('report identity mismatch: ' + key)
    def device_base(value):
        # Vivado timing may omit xc prefix and speed grade shown in utilization.
        value = re.sub(r'^xc', '', value.lower())
        return re.sub(r'-\d[^-]*$', '', value).replace('-', '')
    utilization_device = header(u, 'Device')
    if device_base(utilization_device) != device_base(identities['Device']):
        raise ValueError('report identity mismatch: Device')
    identities['Utilization Device'] = utilization_device
    lines = t.splitlines()
    summary = None
    for i, line in enumerate(lines):
        if line.strip().startswith('WNS(ns)') and 'TPWS' in line:
            for row in lines[i+1:i+7]:
                parts = row.split()
                if len(parts) == 12:
                    try:
                        summary = [float(v) for v in parts]
                    except ValueError:
                        continue
                    break
            if summary is not None:
                break
    if summary is None or not all(math.isfinite(v) for v in summary):
        raise ValueError('unrecognized 12-column timing summary')
    for i in (2, 3, 6, 7, 10, 11):
        if summary[i] < 0 or not summary[i].is_integer():
            raise ValueError('invalid endpoint counts')
    m = re.search(r'\| Clock Summary.*?\n(.*?)(?=\| Intra Clock|\Z)', t, re.S)
    if not m:
        raise ValueError('missing clock summary section')
    clocks = []
    for row in m[1].splitlines():
        c = re.match(r'^\s*(\S+)\s+\{[^}]+\}\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*$', row)
        if c:
            period, mhz = float(c[2]), float(c[3])
            if not all(math.isfinite(v) and v > 0 for v in (period, mhz)):
                raise ValueError('invalid clock')
            clocks.append(dict(name=c[1], period_ns=period, constrained_mhz=mhz))
    if not clocks:
        raise ValueError('unrecognized clock rows')
    resources = {}
    for key, labels in {'luts': ('Slice LUTs', 'CLB LUTs'),
                        'registers': ('Slice Registers', 'CLB Registers'),
                        'bram_tiles': ('Block RAM Tile',),
                        'dsps': ('DSPs', 'DSP48E1', 'DSP48E2')}.items():
        resources[key] = None
        for label in labels:
            found = re.search(r'\|\s*' + re.escape(label) + r'\s*\|\s*([\d,.]+)\s*\|', u)
            if found:
                resources[key] = float(found[1].replace(',', ''))
                break
    if resources['luts'] is None or resources['registers'] is None:
        raise ValueError('unrecognized LUT/register resource rows')
    checks = {}
    for name in ('no_clock', 'unconstrained_internal_endpoints', 'no_input_delay',
                 'no_output_delay', 'partial_input_delay', 'partial_output_delay'):
        found = re.search(r'checking ' + name + r' \((\d+)\)', t)
        if not found:
            raise ValueError('missing constraint check: ' + name)
        checks[name] = int(found[1])
    return dict(identity=identities, resources=resources, clocks=clocks,
                wns_ns=summary[0], tns_ns=summary[1], setup_failing_endpoints=int(summary[2]),
                whs_ns=summary[4], ths_ns=summary[5], hold_failing_endpoints=int(summary[6]),
                wpws_ns=summary[8], tpws_ns=summary[9], pulse_failing_endpoints=int(summary[10]),
                constraint_checks=checks,
                sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (timing, utilization)},
                drc='not checked', cdc='not checked', measured_fmax='not measured')


def evaluate(report, *, max_luts=None, min_wns=0, constraint_waiver=None):
    if not math.isfinite(min_wns) or (max_luts is not None and (not math.isfinite(max_luts) or max_luts < 0)):
        raise ValueError('invalid metric thresholds')
    failed = []
    if report['wns_ns'] < min_wns or report['whs_ns'] < 0 or report['wpws_ns'] < 0:
        failed.append('negative/below-budget timing slack')
    if any(report[k] for k in ('setup_failing_endpoints', 'hold_failing_endpoints', 'pulse_failing_endpoints')):
        failed.append('failing timing endpoints')
    if max_luts is not None and report['resources']['luts'] > max_luts:
        failed.append('LUT budget exceeded')
    nonzero = {k: v for k, v in report['constraint_checks'].items() if v}
    hard = {k: v for k, v in nonzero.items() if k in ('no_clock', 'unconstrained_internal_endpoints')}
    if hard:
        failed.append('missing clocks/unconstrained internal endpoints')
    waiver = constraint_waiver.strip() if constraint_waiver else None
    if nonzero and not hard and not waiver:
        failed.append('IO constraint gaps need documented review')
    result = dict(report)
    result.update(passed=not failed, failures=failed, constraint_waiver=waiver,
                  scope='selected implementation metrics only; no complete design/board acceptance')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    p.add_argument('--max-luts', type=float)
    p.add_argument('--min-wns', type=float, default=0)
    p.add_argument('--constraint-waiver')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = evaluate(parse(a.directory), max_luts=a.max_luts, min_wns=a.min_wns,
                      constraint_waiver=a.constraint_waiver)
    Path(a.output).write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
