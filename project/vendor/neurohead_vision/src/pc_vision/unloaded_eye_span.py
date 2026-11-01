"""One unloaded1200->1500->1800->1500 us sequence; no linkage range claims."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
import struct
import time
from board_network import bind_board_socket
from monitor_protocol import parse_query,valid_crc
from nudge_eye_horizontal import run
from requalify_eye import SETUP
from simulated_board import SimulatedBoard


class UnloadedSocket:
    def __init__(self,sock,session,setup=SETUP):
        self.sock,self.session,self.setup=sock,session,Path(setup)
        self.target=1200;self.sent=0

    def check(self):
        a=self.session
        try:
            if not a['created_at_epoch']<=time.time()<=a['expires_at_epoch']:
                raise RuntimeError('Unloaded session expired')
            if not 0<a['expires_at_epoch']-a['created_at_epoch']<=120:
                raise RuntimeError('Invalid session lifetime')
            raw=self.setup.read_bytes();p=json.loads(raw)
            if hashlib.sha256(raw).hexdigest()!=a['setup_sha256']:
                raise RuntimeError('Joint setup changed; stop commands')
            for k,v in dict(joint='eye_horizontal',servo_model='MG90S',signal_pin=10,
                            linkage_attached=False,motion_inhibited=True).items():
                if type(p.get(k)) is not type(v) or p[k]!=v:
                    raise RuntimeError('Unloaded joint eligibility failed: '+k)
            for k in ('drive_detached','horn_sweep_clear','single_servo_only','supply_4_8v_cv','operator_ready'):
                if a.get(k) is not True:raise RuntimeError('Missing current confirmation: '+k)
        except (OSError,ValueError,KeyError) as exc:
            raise RuntimeError('Invalid unloaded safety record: '+str(exc)) from exc

    def sendto(self,packet,peer):
        if packet[:2]==b'NH':
            self.check()
            if (len(packet)!=16 or not valid_crc(packet) or self.target not in (1200,1800)
                or struct.unpack_from('<HH',packet,6)!=(self.target,1500) or self.sent>=80):
                raise RuntimeError('Unloaded pulse/packet bounds exceeded')
            self.sent+=1
        else:parse_query(packet)
        return self.sock.sendto(packet,peer)

    def __getattr__(self,name):return getattr(self.sock,name)


def execute(session_path,simulated=False,setup=SETUP):
    path=Path(session_path);a=json.loads(path.read_text(encoding='utf-8'))
    if a.get('authority')!=('simulation' if simulated else 'current_operator'):
        raise ValueError('Simulation cannot authorize board')
    guard=UnloadedSocket(None,a,setup);guard.check()
    with path.with_suffix('.claimed').open('x',encoding='utf-8') as f:f.write(str(time.time()))
    sim=SimulatedBoard() if simulated else None
    steps=[];error=None;interface=None
    try:
        peer=sim.start() if sim else ('192.168.10.20',5005)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as raw:
            if sim:raw.bind(('127.0.0.1',0))
            else:interface=bind_board_socket(raw)
            guard.sock=raw
            for target in (1200,1800):
                guard.target=target
                result=run(guard,peer,simulated,target-1500,2)
                steps.append(result)
                if not result['digital_checks_passed']:
                    error=result['error'];break
    except (OSError,RuntimeError) as exc:error=str(exc)
    finally:
        if sim:sim.close()
    record=dict(mode='simulation' if simulated else 'board',purpose='unloaded_servo_response_only',
        requested_sequence_us=[1200,1500,1800,1500],completed_steps=len(steps),
        digital_checks_passed=error is None and len(steps)==2,error=error,steps=steps,
        command_frames_sent=guard.sent,interface_index=interface,
        final_state=steps[-1]['final_state'] if steps else None,
        setup_sha256=a['setup_sha256'],global_motion_inhibit_unchanged=True,
        physical_motion_result='awaiting_operator_observation',
        mechanical_angle_measured=False,loaded_eye_range_verified=False,
        count_conversion='50 MHz:1200us=60000,1500us=75000,1800us=90000',
        boundary='Unloaded shaft only. Does not validate installed eye linkage, angular span or cut servo power.')
    path.with_suffix('.result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true',help='send exactly one bounded sequence to the board')
    parser.add_argument('--drive-detached',action='store_true')
    parser.add_argument('--horn-sweep-clear',action='store_true')
    parser.add_argument('--single-servo-only',action='store_true')
    parser.add_argument('--supply-4-8v-cv',action='store_true')
    parser.add_argument('--operator-ready',action='store_true')
    args=parser.parse_args()
    required=(args.drive_detached,args.horn_sweep_clear,args.single_servo_only,
              args.supply_4_8v_cv,args.operator_ready)
    if not args.send:
        print('PLAN ONLY: J10 pin3 1200 -> 1500 -> 1800 -> 1500 us; no network IO.')
        return
    if not all(required):
        parser.error('--send requires all five current physical-condition confirmations')
    raw=SETUP.read_bytes();now=time.time()
    root=Path(__file__).resolve().parents[2]
    out=root/'data'/'unloaded_span_runs'/f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_board"
    out.mkdir(parents=True,exist_ok=False)
    session=dict(authority='current_operator',created_at_epoch=now,
        expires_at_epoch=now+90,setup_sha256=hashlib.sha256(raw).hexdigest(),
        drive_detached=True,horn_sweep_clear=True,single_servo_only=True,
        supply_4_8v_cv=True,operator_ready=True)
    path=out/'session.json'
    path.write_text(json.dumps(session,indent=2),encoding='utf-8')
    result=execute(path,simulated=False)
    summary={k:v for k,v in result.items() if k!='steps'}
    print(json.dumps(summary,indent=2))
    print(f'Record: {path.with_suffix(".result.json")}')
    raise SystemExit(0 if result['digital_checks_passed'] else 2)


if __name__=='__main__':
    main()
