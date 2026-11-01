"""Ten-second three-position physical response to native ViSP model direction.

Consumes the existing viewer's fresh log; does not reopen the camera or infer
physical angles. Global motion inhibition remains in force for other controls.
"""
import json
import math
from pathlib import Path
import socket
import struct
import time
from board_network import bind_board_socket
from monitor_protocol import parse_query,valid_crc
from nudge_eye_horizontal import run
from requalify_eye import OneTrialSocket,SETUP
from simulated_board import SimulatedBoard


def visual_pulse(row,session_id,now):
    v=row.get('vision') or {};d=row.get('controller_diagnostics') or {}
    if row.get('mode')!='vision_board' or not v.get('running') or v.get('error'):
        raise RuntimeError('Camera/mode unavailable; stop commands')
    if (d.get('backend')!='visp_native' or not d.get('ready') or d.get('error') or
        v.get('source_session_id')!=session_id or d.get('source_session_id')!=session_id):
        raise RuntimeError('Native controller/source changed; stop commands')
    metrics=d.get('metrics') or {}
    if metrics.get('model_only') is not True or metrics.get('native_compute_calls',0)<=0:
        raise RuntimeError('No native model calculation')
    for stamp in (row.get('host_monotonic_s'),v.get('frame_time'),d.get('input_time')):
        if not isinstance(stamp,(int,float)) or not 0<=now-stamp<=.75:
            raise RuntimeError('Stale camera/controller observation; stop commands')
    if v.get('target') is None or row.get('gaze_status')!='tracking':return 1500
    pose=row.get('model_degrees') or {}
    values=[pose.get(k) for k in ('eye_pan','neck_pan')]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
        raise RuntimeError('Invalid model direction')
    direction=sum(values)
    # Three points already observed on this linkage. Model degrees are not
    # interpreted as servo shaft angles; physical tracking polarity is unverified.
    return 1505 if direction>1 else 1495 if direction < -1 else 1500


def latest(path):
    with Path(path).open('rb') as f:
        f.seek(max(0,Path(path).stat().st_size-65536))
        lines=f.read().decode('utf-8',errors='replace').splitlines()
    for line in reversed(lines):
        try:return json.loads(line)
        except ValueError:pass
    raise RuntimeError('No complete viewer frame')


class VisionTrialSocket(OneTrialSocket):
    def check(self):
        super().check()
        p=json.loads(self.setup.read_text(encoding='utf-8'))
        if any(p.get(k) is not True for k in (
            'loaded_plus_5_us_motion_return_operator_confirmed',
            'loaded_minus_5_us_motion_return_operator_confirmed')):
            raise RuntimeError('Both loaded directions must have operator observations')

    def sendto(self,packet,peer):
        if packet[:2]==b'NH':
            if getattr(self,'cancel',None) is not None and self.cancel.is_set():
                raise RuntimeError('Operator stopped visual trial')
            self.check()
            if len(packet)!=16 or not valid_crc(packet):raise RuntimeError('Bad command')
            yaw,pitch=struct.unpack_from('<HH',packet,6)
            if yaw not in (1495,1500,1505) or pitch!=1500 or self.sent>=200:
                raise RuntimeError('Vision trial bounds exceeded')
            self.sent+=1
        else:parse_query(packet)
        return self.sock.sendto(packet,peer)


def execute(session_path,simulated=False,source=None,setup=SETUP,cancel=None):
    path=Path(session_path);a=json.loads(path.read_text(encoding='utf-8'))
    if a.get('authority')!=('simulation' if simulated else 'current_operator'):
        raise ValueError('Wrong trial authority')
    guard=VisionTrialSocket(None,a,setup);guard.cancel=cancel;guard.check()
    inputs=[]
    def pulse():
        row=source() if source else latest(a['viewer_log'])
        value=visual_pulse(row,a['camera_session_id'],time.monotonic())
        inputs.append(dict(time=time.monotonic(),pulse_us=value,
            source_frame_id=row['vision']['frame_id'],native_response=row['controller_diagnostics']['response_sequence'],
            virtual_direction_deg=row['model_degrees']['eye_pan']+row['model_degrees']['neck_pan']))
        return value
    preflight=pulse()  # Reject stale/unavailable input before claiming or opening network.
    inputs.clear()  # Preflight is not a transmitted command sample.
    with path.with_suffix('.claimed').open('x',encoding='utf-8') as f:f.write(str(time.time()))
    sim=SimulatedBoard() if simulated else None
    try:
        peer=sim.start() if sim else ('192.168.10.20',5005)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as raw:
            interface=None
            if sim:raw.bind(('127.0.0.1',0))
            else:interface=bind_board_socket(raw)
            guard.sock=raw
            result=run(guard,peer,simulated,0,10,target_source=pulse)
            result.update(purpose='bounded_three_position_visual_response_not_calibrated_tracking',
                source_inputs=inputs,preflight_pulse_us=preflight,
                interface_index=interface,global_motion_inhibit_unchanged=True,
                physical_angles_measured=False,physical_tracking_polarity_verified=False)
            path.with_suffix('.result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            return result
    finally:
        if sim:sim.close()
