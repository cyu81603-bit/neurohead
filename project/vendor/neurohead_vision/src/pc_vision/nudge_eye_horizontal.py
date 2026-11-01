#!/usr/bin/env python3
"""One bounded +/-25 us eye-horizontal step, then watchdog return to 1500 us.

J10 pin 10 only. Operator must confirm mechanical safety of 1500 us OR physically
detach the linkage for an unloaded check, and leave all other servos disconnected.
Defaults to printing the plan without network IO.
No automatic mechanical verification or profile unlocking is performed.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
import time

from monitor_protocol import make_query, parse_telemetry
from send_neurohead_udp import make_frame
from simulated_board import SimulatedBoard

ROOT = Path(__file__).resolve().parents[2]


def run(sock, peer, simulated, offset, hold_seconds=2, target_source=None):
    rows, sent_count = [], 0
    token = int(time.perf_counter()*1000) & 0xffffffff
    start = time.perf_counter()
    phase = 'initial_readback'
    initial = final = None
    error = cleanup_error = None

    def exchange(packet, stamp, query):
        tx = time.perf_counter()
        sock.sendto(packet, peer)
        deadline = tx+.25
        while time.perf_counter() < deadline:
            sock.settimeout(max(.001, deadline-time.perf_counter()))
            raw, source = sock.recvfrom(2048)
            received = time.perf_counter()
            if source != peer:
                continue
            try:
                state = parse_telemetry(raw)
            except ValueError:
                continue
            if (state['echo_timestamp_ms'] != stamp or state['query'] != query
                    or state['simulated'] != simulated):
                continue
            rows.append(dict(state, phase=phase, elapsed_s=received-start,
                             host_rtt_ms=(received-tx)*1000))
            return state
        raise RuntimeError('No matching telemetry')

    def query():
        nonlocal token
        token = (token+1) & 0xffffffff
        return exchange(make_query(0, token), token, True)

    def observe_return():
        nonlocal phase
        phase = 'commands_stopped_watchdog_return'
        # Allow the actual PL slew limit (8 us/20 ms) plus watchdog and margin.
        # +/-300 us takes about .76 s to slew, in addition to the .3 s watchdog.
        deadline = time.perf_counter()+max(1.0,.3+abs(offset)/8*.020+.5)
        while time.perf_counter() < deadline:
            state = query()
            time.sleep(.025)
        if not (state['status'] & 3 == 3
                and state['output_yaw_us'] == state['output_pitch_us'] == 1500):
            raise RuntimeError('Safe return to 1500/1500 us not confirmed')
        return state

    try:
        initial = query()
        if not (initial['status'] & 1
                and initial['output_yaw_us'] == initial['output_pitch_us'] == 1500):
            raise RuntimeError('Initial safe centre not confirmed; no commands sent')
        sequence = (initial['sequence']+1) & 0xffff if initial['have_sequence'] else 0
        target = 1500+offset
        phase = 'single_eye_step' if target_source is None else 'bounded_visual_response'
        print(f"{'ONE STEP' if target_source is None else 'BOUNDED STREAM'}: eye-horizontal PWM initial={target} us; second channel stays 1500 us; nominal {hold_seconds} seconds.", flush=True)
        for _ in range(20*hold_seconds):
            tx = time.perf_counter()
            if target_source is not None:
                target = target_source()
            token = (token+1) & 0xffffffff
            sent_count += 1
            state = exchange(make_frame(sequence, target, 1500, token), token, False)
            if (not state['have_sequence'] or state['sequence'] != sequence
                    or (state['accepted']-initial['accepted']) & 0xffffffff != sent_count):
                raise RuntimeError('Sequence/counter mismatch; commands stopped')
            if state['invalid'] != initial['invalid'] or state['stale'] != initial['stale']:
                raise RuntimeError('Unexpected rejection or another sender detected')
            sequence = (sequence+1) & 0xffff
            time.sleep(max(0, .05-(time.perf_counter()-tx)))
        reached = (state['output_yaw_us'] == target if target_source is None
                   else abs(state['output_yaw_us']-target)<=8)
        if not (reached and state['output_pitch_us'] == 1500
                and state['status'] & 3 == 0):
            raise RuntimeError('Requested output settings not reached')
        final = observe_return()
        if (final['accepted']-initial['accepted']) & 0xffffffff != sent_count:
            raise RuntimeError('Unexpected command source during return')
    except (OSError, RuntimeError) as exc:
        error = str(exc)
        if sent_count:
            try:
                final = observe_return()
            except (OSError, RuntimeError) as cleanup:
                cleanup_error = str(cleanup)
    return dict(mode='simulation' if simulated else 'board', endpoint=peer,
                joint='eye_horizontal', channel='yaw', j10_signal_pin=10,
                requested_pulse_us=1500+offset if target_source is None else None,
                dynamic_target=target_source is not None, other_channel_pulse_us=1500,
                nominal_hold_s=hold_seconds, command_frames_sent=sent_count,
                digital_checks_passed=error is None, error=error,
                cleanup_error=cleanup_error, initial_state=initial,
                final_state=final, samples=rows,
                physical_motion_result='awaiting_operator_observation',
                boundary='PL register readback and network checks only. No shaft-angle or current measurement. Stop does not remove servo power.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--send', action='store_true')
    p.add_argument('--sim', action='store_true')
    p.add_argument('--center-confirmed', action='store_true')
    p.add_argument('--linkage-detached', action='store_true',
                   help='operator has physically detached the drive linkage; unloaded test only')
    p.add_argument('--single-servo-only', action='store_true')
    p.add_argument('--offset-us', type=int, choices=(-25, 25), default=25)
    p.add_argument('--hold-seconds', type=int, choices=(2, 5), default=2,
                   help='bounded nominal hold; 5 seconds makes a small step easier to observe')
    args = p.parse_args()
    if not (args.send or args.sim):
        print(f'PLAN ONLY: J10 pin3 1500 -> {1500+args.offset_us} -> 1500 us. No network IO.')
        return
    if not args.sim and not ((args.center_confirmed or args.linkage_detached)
                             and args.single_servo_only):
        p.error('--send requires --single-servo-only and either --center-confirmed or --linkage-detached')
    if args.send:
        profile_path = ROOT / 'data/joint_setups/eye_horizontal.json'
        try:
            profile = json.loads(profile_path.read_text(encoding='utf-8'))
            if not isinstance(profile, dict):
                raise ValueError('joint setup must be an object')
        except (OSError, ValueError) as exc:
            p.error(f'Cannot read joint safety state; no motion sent: {exc}')
        if profile.get('motion_inhibited', False):
            p.error('Motion inhibited by joint setup after mechanical fault; inspect before clearing. No network IO.')
    simulator = SimulatedBoard() if args.sim else None
    peer = simulator.start() if simulator else ('192.168.10.20', 5005)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1' if simulator else '192.168.10.10', 0))
            result = run(sock, peer, bool(simulator), args.offset_us, args.hold_seconds)
    finally:
        if simulator:
            simulator.close()
    result['operator_center_confirmed'] = args.center_confirmed
    result['operator_linkage_detached'] = args.linkage_detached
    result['operator_single_servo_only'] = args.single_servo_only
    out = ROOT/'data'/'joint_runs'
    out.mkdir(parents=True, exist_ok=True)
    path = out/f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_eye_horizontal_{result['mode']}.json"
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples', 'initial_state')}, indent=2))
    print(f'Record: {path}')
    raise SystemExit(0 if result['digital_checks_passed'] else 2)


if __name__ == '__main__':
    main()
