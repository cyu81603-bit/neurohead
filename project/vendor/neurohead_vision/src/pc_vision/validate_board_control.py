#!/usr/bin/env python3
"""Bounded UDP/PS/PL acceptance test, ONLY with both actuator signals disconnected.

This actively changes PWM settings. It measures register readback, not pin timing
or shaft angles. No firmware or Flash programming is performed.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import socket
import time

from monitor_protocol import make_query, parse_telemetry
from send_neurohead_udp import make_frame, crc16_ccitt_false
from simulated_board import SimulatedBoard

ROOT = Path(__file__).resolve().parents[2]


class ControlCheck:
    def __init__(self, sock, peer, simulated, hold_seconds=.7):
        self.sock, self.peer, self.simulated = sock, peer, simulated
        self.start = time.perf_counter()
        self.token = int(self.start * 1000) & 0xffffffff
        self.sequence = self.query_sequence = 0
        self.rows, self.checks = [], []
        self.commands_sent = self.injected_frames = 0
        self.phase = 'initial_query'
        self.hold_seconds = hold_seconds

    def timestamp(self):
        self.token = (self.token + 1) & 0xffffffff
        return self.token

    def send_and_receive(self, packet, token, query):
        sent = time.perf_counter()
        self.sock.sendto(packet, self.peer)
        deadline = sent + .5
        while time.perf_counter() < deadline:
            self.sock.settimeout(max(.001, deadline - time.perf_counter()))
            try:
                raw, source = self.sock.recvfrom(2048)
            except socket.timeout:
                break
            received = time.perf_counter()
            if source != self.peer:
                continue
            try:
                state = parse_telemetry(raw)
            except ValueError:
                continue
            if (state['echo_timestamp_ms'] != token or state['query'] != query
                    or state['simulated'] != self.simulated):
                continue
            self.rows.append(dict(state, phase=self.phase,
                                  elapsed_s=received-self.start,
                                  host_rtt_ms=(received-sent)*1000))
            return state
        raise RuntimeError(f'No matching reply in phase {self.phase}')

    def query(self):
        token = self.timestamp()
        packet = make_query(self.query_sequence, token)
        self.query_sequence = (self.query_sequence + 1) & 0xffff
        return self.send_and_receive(packet, token, True)

    def command(self, yaw, pitch):
        token = self.timestamp()
        sequence = self.sequence
        packet = make_frame(sequence, yaw, pitch, token)
        self.commands_sent += 1
        state = self.send_and_receive(packet, token, False)
        if not state['have_sequence'] or state['sequence'] != sequence:
            raise RuntimeError('Command sequence readback mismatch')
        self.sequence = (sequence + 1) & 0xffff
        return state

    def check(self, name, passed, **observed):
        self.checks.append(dict(name=name, passed=bool(passed), observed=observed))
        if not passed:
            raise RuntimeError(f'Acceptance check failed: {name}')

    def hold(self, yaw, pitch, phase):
        self.phase = phase
        # Default: 14 commands at nominal 20 Hz. Longer bounded holds allow
        # the operator to read stable pulse widths on an external scope.
        print(f'{phase}: yaw={yaw} us pitch={pitch} us; nominal hold {self.hold_seconds:g} s', flush=True)
        for _ in range(math.ceil(self.hold_seconds/.05)):
            started = time.perf_counter()
            state = self.command(yaw, pitch)
            time.sleep(max(0, .05-(time.perf_counter()-started)))
        state = self.query()
        self.check(phase, state['output_yaw_us'] == yaw
                   and state['output_pitch_us'] == pitch and state['status'] & 3 == 0,
                   output_yaw_us=state['output_yaw_us'],
                   output_pitch_us=state['output_pitch_us'], status=state['status'])
        return state

    def inject(self, packet):
        # Invalid / stale frames intentionally have no command acknowledgement.
        self.sock.sendto(packet, self.peer)
        self.injected_frames += 1

    def finish_safe(self):
        self.phase = 'query_only_watchdog_return'
        deadline = time.perf_counter() + 1.0
        state = None
        while time.perf_counter() < deadline:
            state = self.query()
            time.sleep(.025)
        self.check('watchdog_safe_and_centered', state['status'] & 3 == 3
                   and state['output_yaw_us'] == 1500
                   and state['output_pitch_us'] == 1500,
                   status=state['status'], output_yaw_us=state['output_yaw_us'],
                   output_pitch_us=state['output_pitch_us'])
        return state

    def run(self):
        initial = self.query()
        self.check('initial_safe_and_centered', initial['status'] & 1 == 1
                   and initial['output_yaw_us'] == initial['output_pitch_us'] == 1500,
                   status=initial['status'], output_yaw_us=initial['output_yaw_us'],
                   output_pitch_us=initial['output_pitch_us'])
        self.sequence = (initial['sequence']+1) & 0xffff if initial['have_sequence'] else 0
        self.hold(1550, 1450, 'independent_targets_a')
        state = self.hold(1450, 1550, 'independent_targets_b')
        last_sequence = state['sequence']
        counters = (state['accepted'], state['invalid'], state['stale'])

        self.phase = 'reject_bad_crc'
        bad = bytearray(make_frame(self.sequence, 1500, 1500, self.timestamp()))
        bad[-1] ^= 1
        self.inject(bad)
        state = self.query()
        self.check('bad_crc_rejected', (state['accepted'], state['invalid'], state['stale'])
                   == (counters[0], (counters[1]+1) & 0xffffffff, counters[2]))

        self.phase = 'reject_out_of_range'
        # Form a valid-CRC command that the PS must reject before AXI commit.
        bad = bytearray(make_frame(self.sequence, 1500, 1500, self.timestamp()))
        bad[6:8] = (599).to_bytes(2, 'little')
        bad[14:16] = crc16_ccitt_false(bad[:14]).to_bytes(2, 'little')
        self.inject(bad)
        state = self.query()
        self.check('out_of_range_rejected_by_ps', (state['accepted'], state['invalid'], state['stale'])
                   == (counters[0], (counters[1]+2) & 0xffffffff, counters[2]))

        self.phase = 'reject_duplicate_sequence'
        self.inject(make_frame(last_sequence, 1500, 1500, self.timestamp()))
        state = self.query()
        self.check('duplicate_sequence_rejected',
                   (state['accepted'], state['invalid'], state['stale'])
                   == (counters[0], (counters[1]+2) & 0xffffffff, (counters[2]+1) & 0xffffffff)
                   and state['target_yaw_us'] == 1450 and state['target_pitch_us'] == 1550)

        state = self.finish_safe()
        self.check('no_unexpected_commands',
                   (state['accepted']-initial['accepted']) & 0xffffffff == self.commands_sent)
        self.check('query_traffic_did_not_refresh_watchdog',
                   (state['watchdog_events']-initial['watchdog_events']) & 0xffffffff >= 1,
                   initial_events=initial['watchdog_events'], final_events=state['watchdog_events'])
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.10.20')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--bind-ip', default='192.168.10.10')
    parser.add_argument('--outputs-disconnected', action='store_true',
                        help='operator assertion: both PWM outputs disconnected from actuators; servo power off')
    parser.add_argument('--sim', action='store_true')
    parser.add_argument('--hold-seconds', type=float, default=.7,
                        help='nominal hold per target pair, 0.7 to 10 seconds; longer for scope readings')
    args = parser.parse_args()
    if not .7 <= args.hold_seconds <= 10:
        parser.error('--hold-seconds must be between 0.7 and 10')
    if not args.sim and not args.outputs_disconnected:
        parser.error('This active bench test requires --outputs-disconnected; never run on connected actuators.')
    simulator = SimulatedBoard() if args.sim else None
    peer = simulator.start() if simulator else (socket.gethostbyname(args.host), args.port)
    error, final_state, cleanup_error = None, None, None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1' if simulator else args.bind_ip, 0))
        test = ControlCheck(sock, peer, bool(simulator), args.hold_seconds)
        try:
            final_state = test.run()
        except (OSError, RuntimeError) as exc:
            error = str(exc)
        finally:
            # Stop command traffic; even failed tests must attempt safe readback.
            if error and test.commands_sent:
                try:
                    final_state = test.finish_safe()
                except (OSError, RuntimeError) as exc:
                    cleanup_error = str(exc)
            if simulator:
                simulator.close()
    result = dict(mode='simulation' if simulator else 'board', endpoint=peer,
                  operator_assertion_outputs_disconnected=bool(args.outputs_disconnected),
                  passed=error is None, error=error, cleanup_error=cleanup_error,
                  command_frames_sent=test.commands_sent, injected_frames=test.injected_frames,
                  nominal_hold_seconds_per_pair=args.hold_seconds,
                  checks=test.checks, final_state=final_state, samples=test.rows,
                  boundary='Active no-actuator test. PL register readback only; not physical PWM, joint angles or precise watchdog latency.')
    out = ROOT/'data'/'board_control_checks'
    out.mkdir(parents=True, exist_ok=True)
    path = out/f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{result['mode']}.json"
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'samples'}, indent=2))
    print(f'Record: {path}')
    raise SystemExit(0 if result['passed'] else 2)


if __name__ == '__main__':
    main()
