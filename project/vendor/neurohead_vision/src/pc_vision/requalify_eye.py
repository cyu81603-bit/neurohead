"""One recorded +/-5 us requalification after repair; never unlocks normal control."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
import struct
import time

from board_network import bind_board_socket
from monitor_protocol import parse_query, valid_crc
from nudge_eye_horizontal import ROOT, run
from simulated_board import SimulatedBoard

SETUP = ROOT/'data/joint_setups/eye_horizontal.json'


class OneTrialSocket:
    def __init__(self, sock, session, setup=SETUP):
        self.sock, self.session, self.setup = sock, session, Path(setup)
        self.sent = 0

    def check(self):
        a = self.session
        if not a['created_at_epoch'] <= time.time() <= a['expires_at_epoch']:
            raise RuntimeError('Trial expired; no further commands')
        if a['expires_at_epoch']-a['created_at_epoch'] > 120:
            raise RuntimeError('Trial lifetime exceeds 120 seconds')
        raw = self.setup.read_bytes()
        p = json.loads(raw)
        if hashlib.sha256(raw).hexdigest() != a['setup_sha256']:
            raise RuntimeError('Joint setup changed; trial stopped')
        expected = dict(joint='eye_horizontal',servo_model='MG90S',signal_pin=10,
                        linkage_attached=True,motion_inhibited=True,
                        binding_repair_operator_reported=True)
        if any(type(p.get(k)) is not type(v) or p[k]!=v for k,v in expected.items()):
            raise RuntimeError('Not the recorded repaired/reassembled joint')
        for key in ('loaded_neutral_stable','supply_cv','single_servo_only','operator_ready'):
            if a.get(key) is not True:
                raise RuntimeError('Missing current physical confirmation: '+key)
        if type(a.get('offset_us')) is not int or a['offset_us'] not in (-5,5):
            raise RuntimeError('Only a single +/-5 us trial is supported')

    def sendto(self, packet, peer):
        if packet[:2] == b'NH':
            self.check()
            if (len(packet)!=16 or not valid_crc(packet) or
                struct.unpack_from('<HH',packet,6)!=(1500+self.session['offset_us'],1500) or self.sent>=40):
                raise RuntimeError('Trial packet or count exceeded')
            self.sent += 1
        else:
            parse_query(packet)  # Queries remain possible after timeout/revocation.
        return self.sock.sendto(packet,peer)

    def __getattr__(self,name): return getattr(self.sock,name)


def execute(session_path, simulated=False, setup=SETUP):
    session_path=Path(session_path)
    a=json.loads(session_path.read_text(encoding='utf-8'))
    if a.get('authority') != ('simulation' if simulated else 'current_operator'):
        raise ValueError('Simulation records cannot authorize board IO')
    simulator=SimulatedBoard() if simulated else None
    guard=OneTrialSocket(None,a,setup)
    guard.check()
    # Exclusive creation consumes the trial even if connection or execution fails.
    with session_path.with_suffix('.claimed').open('x',encoding='utf-8') as claim:
        claim.write(str(time.time()))
    try:
        peer=simulator.start() if simulator else ('192.168.10.20',5005)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as raw:
            interface=None
            if simulator: raw.bind(('127.0.0.1',0))
            else: interface=bind_board_socket(raw)
            guard.sock=raw
            result=run(guard,peer,simulated,a['offset_us'],2)
            result.update(purpose='single_repaired_linkage_requalification',
                authorization=str(session_path),interface_index=interface,
                global_motion_inhibit_unchanged=True,mechanical_range_verified=False)
            session_path.with_suffix('.result.json').write_text(
                json.dumps(result,indent=2),encoding='utf-8')
            return result
    finally:
        if simulator: simulator.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--send',action='store_true')
    p.add_argument('--session',type=Path)
    p.add_argument('--create-current-session',action='store_true')
    p.add_argument('--offset-us',type=int,choices=(-5,5))
    p.add_argument('--loaded-neutral-stable',action='store_true')
    p.add_argument('--supply-cv',action='store_true')
    p.add_argument('--single-servo-only',action='store_true')
    p.add_argument('--operator-ready',action='store_true')
    args=p.parse_args()
    if not args.send:
        print('PLAN ONLY: one +/-5 us, 2 seconds, watchdog return; no network IO.')
        return
    if args.create_current_session:
        if args.session is not None or args.offset_us not in (-5,5):
            p.error('--create-current-session requires --offset-us and no --session')
        if not all((args.loaded_neutral_stable,args.supply_cv,
                    args.single_servo_only,args.operator_ready)):
            p.error('current session requires all four physical confirmations')
        raw=SETUP.read_bytes();now=time.time()
        out=ROOT/'data'/'joint_runs'/f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_eye_requalification"
        out.mkdir(parents=True,exist_ok=False)
        args.session=out/'session.json'
        args.session.write_text(json.dumps(dict(authority='current_operator',
            created_at_epoch=now,expires_at_epoch=now+90,
            setup_sha256=hashlib.sha256(raw).hexdigest(),offset_us=args.offset_us,
            loaded_neutral_stable=True,supply_cv=True,single_servo_only=True,
            operator_ready=True),indent=2),encoding='utf-8')
    if args.session is None: p.error('--send requires a fresh one-use operator session')
    try: result=execute(args.session)
    except (OSError,ValueError,RuntimeError,KeyError) as exc: p.exit(2,str(exc)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','initial_state')},indent=2))
    raise SystemExit(0 if result['digital_checks_passed'] else 2)


if __name__=='__main__': main()
