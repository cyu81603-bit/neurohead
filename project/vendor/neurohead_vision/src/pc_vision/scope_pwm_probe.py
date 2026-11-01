#!/usr/bin/env python3
"""Hold J10 pin 10 at 1475 us for scope reading, with servo signals disconnected.

This is an electrical diagnostic, never a connected-actuator range test.
Default: print plan only. Reuses the checked sequence/counter/watchdog path.
"""
import argparse
from datetime import datetime
import json
import socket

from nudge_eye_horizontal import ROOT, run
from simulated_board import SimulatedBoard


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--send', action='store_true')
    modes.add_argument('--sim', action='store_true')
    p.add_argument('--servo-power-disconnected', action='store_true')
    p.add_argument('--servo-signals-disconnected', action='store_true')
    p.add_argument('--hold-seconds', type=int, choices=(5, 30, 60), default=30)
    args = p.parse_args()
    if not (args.send or args.sim):
        print(f'PLAN ONLY: J10 pin3=1475 us for nominal {args.hold_seconds}s, then watchdog returns to 1500 us; pin4 stays 1500 us. No network IO.')
        return
    if args.send and not (args.servo_power_disconnected and args.servo_signals_disconnected):
        p.error('--send requires external servo power OFF and both servo signal outputs disconnected')
    simulator = SimulatedBoard() if args.sim else None
    peer = simulator.start() if simulator else ('192.168.10.20', 5005)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1' if simulator else '192.168.10.10', 0))
            result = run(sock, peer, bool(simulator), -25, args.hold_seconds)
    finally:
        if simulator:
            simulator.close()
    result['test_kind'] = 'scope_only_actuators_disconnected'
    result['physical_motion_result'] = 'not_applicable_actuators_disconnected'
    result['operator_servo_power_disconnected'] = args.servo_power_disconnected
    result['operator_servo_signals_disconnected'] = args.servo_signals_disconnected
    result['measured_positive_width_us'] = None
    result['physical_waveform_result'] = 'awaiting_operator_measurement'
    out = ROOT / 'data/scope_checks'
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_scope_hold_{result['mode']}.json"
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('samples', 'initial_state')}, indent=2))
    print(f'Record: {path}')
    raise SystemExit(0 if result['digital_checks_passed'] else 2)


if __name__ == '__main__':
    main()
