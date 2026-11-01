#!/usr/bin/env python3
"""Query monitor telemetry without sending any PWM command."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
import statistics
import time
from monitor_protocol import make_query, parse_telemetry
from simulated_board import SimulatedBoard
from board_network import bind_board_socket

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='192.168.10.20')
    p.add_argument('--port', type=int, default=5005)
    p.add_argument('--bind-ip', default='192.168.10.10', help='dedicated PC Ethernet address')
    p.add_argument('--duration', type=float, default=5)
    p.add_argument('--sim', action='store_true')
    args = p.parse_args()
    interface_index=None
    if not 0 < args.duration <= 60:
        p.error('duration must be between 0 and 60 seconds')
    sim = SimulatedBoard() if args.sim else None
    peer = sim.start() if sim else (socket.gethostbyname(args.host), args.port)
    rows, sent_count, error = [], 0, None
    started = time.monotonic()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Do not let a VPN/default route silently replace the board link.
            if sim:s.bind(('127.0.0.1',0))
            else:interface_index=bind_board_socket(s,args.bind_ip)
            s.settimeout(.25)
            while time.monotonic()-started < args.duration:
                sent = time.monotonic()
                token = int(sent*1000) & 0xffffffff
                sent_ns = time.perf_counter_ns()
                s.sendto(make_query(sent_count & 0xffff, token), peer)
                sent_count += 1
                deadline = sent+.25
                while time.monotonic() < deadline:
                    try:
                        raw, source = s.recvfrom(2048)
                        received_ns = time.perf_counter_ns()
                    except socket.timeout:
                        break
                    if source != peer:
                        continue
                    try:
                        row = parse_telemetry(raw)
                    except ValueError:
                        continue
                    if (not row['query'] or row['echo_timestamp_ms'] != token
                            or row['simulated'] != bool(sim)):
                        continue
                    row.update(elapsed_s=time.monotonic()-started,
                               host_rtt_ms=(received_ns-sent_ns)/1_000_000)
                    rows.append(row)
                    break
                remaining = min(.1-(time.monotonic()-sent), args.duration-(time.monotonic()-started))
                if remaining > 0:
                    time.sleep(remaining)
    except OSError as exc:
        error = str(exc)
    finally:
        if sim:
            sim.close()
    rtts = sorted(row['host_rtt_ms'] for row in rows)
    result = dict(mode='simulation' if sim else 'board', endpoint=peer,
                  explicit_ipv4_interface_index=interface_index,
                  sent_queries=sent_count, matched_replies=len(rows),
                  sent_motion_commands=0, network_error=error, samples=rows,
                  unmatched_queries=sent_count-len(rows),
                  reply_rate=len(rows)/sent_count if sent_count else None,
                  rtt_clock='time.perf_counter_ns',
                  rtt_definition='host send to matched receive; includes host scheduling; not one-way or camera-to-motion latency',
                  rtt_ms=dict(min=rtts[0], median=statistics.median(rtts),
                              p99=rtts[max(0, (99*len(rtts)+99)//100-1)], max=rtts[-1]) if rtts else None,
                  boundary='PL register readback is not a measured shaft angle or PWM waveform')
    out = ROOT/'data/connection_checks'
    out.mkdir(parents=True, exist_ok=True)
    path = out/f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{result['mode']}.json"
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f"Queries={sent_count} Replies={len(rows)} Motion commands=0 Mode={result['mode']}")
    print(f'Record: {path}')
    print(f"RTT summary (ms): {result['rtt_ms']}")
    if rows:
        print(json.dumps(rows[-1], indent=2))
    raise SystemExit(0 if rows else 2)


if __name__ == '__main__':
    main()
