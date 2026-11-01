"""Neck-yaw midpoint: decoupled 2s test or operator-requested loaded 0.2s pulse.
Unknown initial shaft position is never inferred from PWM register readback.
"""
import argparse,hashlib,json,sys,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from eye_camera_feedback import acquire_run_lock
ROOT=Path(__file__).resolve().parents[2]
GUARD=Path(r'F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json')
GUARD_HASH='1051e489ce396a0d24b937b8a3dd9aaeb9a60f4fab61e0a324df33925a87ecb6'
CHANNEL=18
ALLOWED_IDLE_CONFIG=3|(7<<18)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','operator-ready','decoupled','head-supported','loaded-first-pulse'):
        parser.add_argument('--'+name,action='store_true')
    parser.add_argument('--out',type=Path)
    a=parser.parse_args()
    if a.decoupled and a.loaded_first_pulse:
        parser.error('select decoupled or loaded first pulse, not both')
    frame_count=4 if a.loaded_first_pulse else 40
    result=dict(purpose='neck_yaw_loaded_first_pulse' if a.loaded_first_pulse else 'neck_yaw_decoupled_electrical_midpoint',channel=CHANNEL,
        connector='J10 Pin21',target_pwm_us=1500,duration_s=frame_count*.05,
        initial_shaft_position_unknown=a.loaded_first_pulse,
        initial_physical_travel_is_bounded=False,
        loaded_first_pulse=a.loaded_first_pulse,
        shaft_angle_measured=False,physical_observation=None,
        mechanical_forward_reference_verified=False)
    if not a.run:
        print(json.dumps(dict(dry_run=True,**result,
            requires='current wiring and power, supported head, either decoupled output or explicit loaded-first-pulse request')))
        return
    if not (a.operator_ready and a.head_supported and (a.decoupled or a.loaded_first_pulse)):
        raise ValueError('current readiness, supported head and decoupled or loaded-first-pulse mode required; no network IO')
    if a.loaded_first_pulse:
        profile=json.loads((ROOT/'config/neck_follow.json').read_text(encoding='utf-8-sig'))
        if not profile.get('loaded_first_pulse_requested_by_operator'):
            raise ValueError('explicit operator request for loaded first pulse required; no network IO')
    if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:
        raise ValueError('original eye guard changed')
    output=a.out or ROOT/'build'/('neck_yaw_midpoint_'+str(time.time_ns())+'.result.json')
    samples=[]
    with acquire_run_lock(ROOT/'build/eye_feedback.lock'):
        client=Client(bind='192.168.10.10',timeout=.05 if a.loaded_first_pulse else 1)
        try:
            state=client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~ALLOWED_IDLE_CONFIG:
                raise RuntimeError('board not idle; no actuator writes sent')
        except BaseException:
            client.close();raise
        try:
            seq=client.next_sequence()
            state=client.exchange(config(seq,CHANNEL,1500,1500,1500,5,False))
            if state['sequence']!=seq:raise RuntimeError('configuration not acknowledged')
            started=time.perf_counter()
            for i in range(frame_count):
                if time.perf_counter()-started>(.25 if a.loaded_first_pulse else 5):raise RuntimeError('midpoint test deadline exceeded')
                if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:
                    raise RuntimeError('original eye guard changed')
                pulses=[0]*22;pulses[CHANNEL]=1500;seq=client.next_sequence()
                state=client.exchange(motion(seq,1<<CHANNEL,pulses,int(time.monotonic()*1000)))
                if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~(1<<CHANNEL):
                    raise RuntimeError('midpoint command rejected')
                samples.append(dict(requested_us=1500,output_pwm_setting_us=state['output_us'][CHANNEL]))
                time.sleep(max(0,started+(i+1)*.05-time.perf_counter()))
            if samples[-1]['output_pwm_setting_us']!=1500:
                raise RuntimeError('midpoint PWM setting not reached')
            result['digital_checks_passed']=True
        except BaseException as exc:
            result['interruption_reason']=str(exc);raise
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state['active_mask'] or state['status']:raise RuntimeError('stop not acknowledged')
                result['final']=state
            finally:
                client.close()
                result.update(motion_frames=len(samples),samples=samples,
                    original_eye_guard_unchanged=hashlib.sha256(GUARD.read_bytes()).hexdigest()==GUARD_HASH)
                output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RESULT',output)
if __name__=='__main__':main()