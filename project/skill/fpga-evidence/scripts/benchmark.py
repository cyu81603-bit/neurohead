"""Measure an explicitly supplied repeatable command; timing includes process startup."""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import time


def measure(command, output, *, samples=10, warmups=0, timeout=30):
    if not command or not all(isinstance(v, str) and v for v in command):
        raise ValueError('nonempty argv command required')
    if type(samples) is not int or samples < 1 or type(warmups) is not int or warmups < 0:
        raise ValueError('positive samples/nonnegative warmups required')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('finite positive timeout required')
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    runs, timings, failed = [], [], False
    for index in range(warmups + samples):
        started = time.perf_counter()
        try:
            process = subprocess.run(command, capture_output=True, timeout=timeout, shell=False)
            entry = dict(index=index, warmup=index < warmups, returncode=process.returncode,
                         timed_out=False, elapsed_ms=(time.perf_counter()-started)*1000)
            (out/f'run-{index:04d}.stdout').write_bytes(process.stdout)
            (out/f'run-{index:04d}.stderr').write_bytes(process.stderr)
            failed = process.returncode != 0
        except subprocess.TimeoutExpired as exc:
            entry = dict(index=index, warmup=index < warmups, returncode=None,
                         timed_out=True, elapsed_ms=(time.perf_counter()-started)*1000)
            (out/f'run-{index:04d}.stdout').write_bytes(exc.stdout or b'')
            (out/f'run-{index:04d}.stderr').write_bytes(exc.stderr or b'')
            failed = True
        except OSError as exc:
            entry = dict(index=index, warmup=index < warmups, returncode=None,
                         timed_out=False, error=str(exc), elapsed_ms=(time.perf_counter()-started)*1000)
            failed = True
        runs.append(entry)
        if failed:
            break
        if index >= warmups:
            timings.append(entry['elapsed_ms'])
    with (out/'latency.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['latency_ms'])
        writer.writerows([v] for v in timings)
    sorted_times = sorted(timings)
    result = dict(passed=not failed, command=command, requested_samples=samples,
                  completed_samples=len(timings), warmups=warmups, timeout_seconds=timeout,
                  median_ms=statistics.median(timings) if timings else None,
                  p95_ms=sorted_times[math.ceil(.95*len(sorted_times))-1] if timings else None,
                  runs=runs, scope='host command wall time, including process startup and all command work')
    (out/'benchmark.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--samples', type=int, default=10)
    p.add_argument('--warmups', type=int, default=0)
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    result = measure(command, a.output, samples=a.samples, warmups=a.warmups, timeout=a.timeout)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
