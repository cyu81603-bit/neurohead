"""Bounded unloaded MG90S diagnosis; never clears the loaded-linkage fault.

Default: plan only. Real IO requires current operator confirmations. The existing
calibration GUI and nudge tool remain inhibited for the assembled mechanism.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket

from nudge_eye_horizontal import run
from simulated_board import SimulatedBoard

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT/'data/joint_setups/eye_horizontal.json'
KNOWN_STATUS = 'motion_inhibited_drive_disconnected_eye_linkage_free_inspect_drive_joint'


def check_detached_setup(path=SETUP):
    p = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(p, dict):
        raise ValueError('Malformed joint setup')
    expected = dict(joint='eye_horizontal', servo_model='MG90S', signal_pin=10,
                    linkage_attached=False, motion_inhibited=True,
                    passive_eye_linkage_free_drive_disconnected=True,
                    unloaded_plus_25_us_motion_return_verified=True,
                    unloaded_minus_25_us_motion_return_verified=True,
                    status=KNOWN_STATUS)
    for key, value in expected.items():
        if type(p.get(key)) is not type(value) or p[key] != value:
            raise ValueError(f'Detached diagnosis not eligible: {key}')


class GuardedSocket:
    """Recheck scoped eligibility before every command, including mid-run edits."""
    def __init__(self, sock, guard):
        self.sock, self.guard = sock, guard

    def sendto(self, packet, peer):
        if packet[:2] == b'NH':
            try:
                self.guard()
            except (OSError, ValueError) as exc:
                raise RuntimeError(f'Diagnostic stopped: {exc}') from exc
        return self.sock.sendto(packet, peer)

    def __getattr__(self, name):
        return getattr(self.sock, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--send', action='store_true')
    mode.add_argument('--sim', action='store_true')
    parser.add_argument('--linkage-detached', action='store_true')
    parser.add_argument('--single-servo-only', action='store_true')
    parser.add_argument('--powered-neutral-stable', action='store_true')
    parser.add_argument('--groups', type=int, choices=(1, 3), default=1)
    args = parser.parse_args()
    offsets = [-25, 25]*args.groups
    if not (args.send or args.sim):
        print(f'PLAN ONLY: {args.groups} groups; each 1500->1475->1500->1525->1500 us.')
        print('J10 pin3 only; detached single MG90S; other servo signals disconnected. No network IO.')
        return
    if args.send:
        if not (args.linkage_detached and args.single_servo_only and args.powered_neutral_stable):
            parser.error('Real diagnosis requires all three current physical-state confirmations; no network IO')
        try:
            check_detached_setup()
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    before = hashlib.sha256(SETUP.read_bytes()).hexdigest()
    report = dict(mode='board' if args.send else 'simulation',
                  purpose='detached_single_servo_diagnosis_only',
                  loaded_linkage_fault_cleared=False, other_channel_us=1500,
                  requested_groups=args.groups, results=[],
                  operator_confirmations=dict(linkage_detached=args.linkage_detached,
                      single_servo_only=args.single_servo_only,
                      powered_neutral_stable=args.powered_neutral_stable),
                  physical_observation='awaiting_operator' if args.send else 'not_applicable',
                  angle_mapping=None, mechanical_range_verified=False,
                  boundary='Telemetry is PL output setting, not measured angle or scope waveform. Stop does not cut power.')
    out = ROOT/'data/detached_diagnostics'
    out.mkdir(parents=True, exist_ok=True)
    path = out/f"{datetime.now():%Y%m%d_%H%M%S_%f}_{report['mode']}.json"

    def save():
        report['joint_fault_file_unchanged'] = hashlib.sha256(SETUP.read_bytes()).hexdigest() == before
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    sim = SimulatedBoard() if args.sim else None
    try:
        peer = sim.start() if sim else ('192.168.10.20', 5005)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as raw:
            raw.bind(('127.0.0.1' if sim else '192.168.10.10', 0))
            sock = raw if sim else GuardedSocket(raw, check_detached_setup)
            for step, offset in enumerate(offsets, 1):
                print(f'Step {step}/{len(offsets)}; mode={report["mode"]}', flush=True)
                result = run(sock, peer, bool(sim), offset, hold_seconds=2)
                report['results'].append(result)
                save()
                if not result['digital_checks_passed']:
                    raise RuntimeError(result['error'])
                print('PL setting reached target and returned to 1500/1500 us.', flush=True)
        report['status'] = 'digital_checks_passed_operator_observation_pending' if args.send else 'simulation_passed'
    except (KeyboardInterrupt, OSError, RuntimeError) as exc:
        report['status'] = 'aborted'
        report['error'] = str(exc) or 'KeyboardInterrupt'
    finally:
        if sim:
            sim.close()
        save()
    print(f'Record: {path}', flush=True)
    print(json.dumps({k:v for k,v in report.items() if k!='results'}, ensure_ascii=False, indent=2))
    raise SystemExit(2 if report['status']=='aborted' else 0)


if __name__ == '__main__':
    main()
