"""Numeric CSV comparison with explicit tolerances, provenance and optional timing."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


def load(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if len(rows) < 2 or not rows[0] or len(set(rows[0])) != len(rows[0]):
        raise ValueError('nonempty CSV with unique headers required')
    header = rows[0]
    values = []
    for row in rows[1:]:
        if len(row) != len(header):
            raise ValueError('ragged CSV')
        value = [float(v) for v in row]
        if not all(math.isfinite(v) for v in value):
            raise ValueError('NaN/Inf not accepted')
        values.append(value)
    return header, values


def compare(expected, actual, *, atol=0, rtol=0, latency=None):
    if any(not math.isfinite(v) or v < 0 for v in (atol, rtol)):
        raise ValueError('finite nonnegative tolerances required')
    eh, ev = load(expected)
    ah, av = load(actual)
    if eh != ah or len(ev) != len(av):
        raise ValueError('CSV header/shape mismatch')
    failures, max_abs, max_rel, rel_at_zero = [], 0.0, 0.0, False
    for i, (erow, arow) in enumerate(zip(ev, av)):
        for j, (e, a) in enumerate(zip(erow, arow)):
            error = abs(a - e)
            if not math.isfinite(error):
                raise ValueError('comparison overflow; use a scaled/exact comparator')
            max_abs = max(max_abs, error)
            if e:
                relative = error / abs(e)
                if not math.isfinite(relative):
                    raise ValueError('relative error overflow')
                max_rel = max(max_rel, relative)
            elif error:
                rel_at_zero = True
            if error > atol + rtol * abs(e):
                failures.append(dict(row=i + 2, column=eh[j], expected=e, actual=a, absolute_error=error))
    result = dict(passed=not failures, rows=len(ev), elements=len(ev)*len(eh),
                  atol=atol, rtol=rtol, max_absolute_error=max_abs,
                  max_relative_error_nonzero_reference=max_rel,
                  nonzero_error_at_zero_reference=rel_at_zero,
                  failure_count=len(failures), first_failures=failures[:20],
                  sha256={name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                          for name, p in [('expected', expected), ('actual', actual)]},
                  latency='not measured')
    if latency:
        header, rows = load(latency)
        if header != ['latency_ms'] or any(row[0] < 0 for row in rows):
            raise ValueError('latency CSV needs nonnegative latency_ms column')
        samples = sorted(row[0] for row in rows)
        result['latency'] = dict(samples=len(samples), median_ms=statistics.median(samples),
                                 p95_ms=samples[math.ceil(.95*len(samples))-1],
                                 method='nearest-rank p95; caller must state measurement boundary',
                                 sha256=hashlib.sha256(Path(latency).read_bytes()).hexdigest())
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('expected')
    p.add_argument('actual')
    p.add_argument('--atol', type=float, default=0)
    p.add_argument('--rtol', type=float, default=0)
    p.add_argument('--latency')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = compare(a.expected, a.actual, atol=a.atol, rtol=a.rtol, latency=a.latency)
    Path(a.output).write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result['passed'] else 1)
